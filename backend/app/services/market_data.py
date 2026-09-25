"""Market data service.

Internal interface through which Strategy/Backtest/Trading engines request
market data. It depends only on the BrokerAdapter and the domain DTOs, so those
engines never touch a broker SDK. Handles timeframe conversion, chunking of long
ranges, merging, sorting and de-duplication of candles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.brokers.base import BrokerAdapter
from app.brokers.tinvest_errors import (
    InstrumentNotFoundError,
    InvalidRequestError,
    ResourceNotFoundError,
)
from app.domain.marketdata import (
    Candle,
    LastPrice,
    MarketDataUnavailable,
    MarketSnapshot,
    Timeframe,
)

# Maximum range (seconds) fetched per broker request for a given timeframe.
# Based on the external provider's per-interval maximum so that a single request
# never returns more candles than the provider allows.
_TIMEFRAME_CHUNK_SECONDS = {
    Timeframe.MIN_1: 86400,  # 1 day
    Timeframe.MIN_5: 7 * 86400,  # 1 week
    Timeframe.MIN_15: 21 * 86400,  # 3 weeks
    Timeframe.MIN_30: 21 * 86400,  # 3 weeks
    Timeframe.HOUR_1: 90 * 86400,  # 3 months
    Timeframe.HOUR_4: 90 * 86400,  # 3 months
    Timeframe.DAY_1: 2190 * 86400,  # 6 years
    Timeframe.WEEK_1: 5 * 365 * 86400,  # 5 years
    Timeframe.MONTH_1: 10 * 365 * 86400,  # 10 years
}

# Candidate interval (fallback used to validate supported timeframes).
_SUPPORTED = set(Timeframe)

# Seconds per timeframe, used to size the snapshot retrieval window.
_TIMEFRAME_SECONDS = {
    Timeframe.MIN_1: 60,
    Timeframe.MIN_5: 300,
    Timeframe.MIN_15: 900,
    Timeframe.MIN_30: 1800,
    Timeframe.HOUR_1: 3600,
    Timeframe.HOUR_4: 14400,
    Timeframe.DAY_1: 86400,
    Timeframe.WEEK_1: 7 * 86400,
    Timeframe.MONTH_1: 30 * 86400,
}


class MarketDataService:
    """Provides normalized market data from a broker adapter."""

    def __init__(self, broker: BrokerAdapter) -> None:
        self._broker = broker

    async def get_last_price(self, figi: str) -> LastPrice:
        """Return the normalized last trade price."""
        try:
            return await self._broker.get_last_price(figi)
        except ResourceNotFoundError as exc:
            raise InstrumentNotFoundError(f"Instrument not found: {figi}") from exc

    async def get_candles(
        self,
        figi: str,
        timeframe: Timeframe,
        from_: datetime,
        to: datetime,
    ) -> list[Candle]:
        """Return sorted, de-duplicated historical candles.

        Long ranges are fetched in chunks and merged into a single normalized,
        chronologically sorted list with no duplicate timestamps.
        """
        if timeframe not in _SUPPORTED:
            raise InvalidRequestError(f"Unsupported timeframe: {timeframe}")
        if from_ >= to:
            raise InvalidRequestError("'from' must be earlier than 'to'")

        chunk_seconds = _TIMEFRAME_CHUNK_SECONDS[timeframe]
        merged: list[Candle] = []
        try:
            for chunk_from, chunk_to in self._split_range(from_, to, chunk_seconds):
                merged.extend(await self._broker.get_candles(figi, timeframe, chunk_from, chunk_to))
        except ResourceNotFoundError as exc:
            raise InstrumentNotFoundError(f"Instrument not found: {figi}") from exc

        return self._sort_and_dedupe(merged)

    async def get_snapshot(
        self, figi: str, timeframe: Timeframe, lookback_bars: int
    ) -> MarketSnapshot:
        """Return a broker-neutral live market snapshot (last price + candles).

        Assembled exclusively from real broker data: the last trade price and
        the most recent ``lookback_bars`` candles for the instrument and
        timeframe. No synthetic value is substituted: a missing or
        non-positive last price, or an empty candle history, raises
        |MarketDataUnavailable| instead.
        """
        if timeframe not in _SUPPORTED:
            raise InvalidRequestError(f"Unsupported timeframe: {timeframe}")
        if lookback_bars is None or lookback_bars < 1:
            raise InvalidRequestError("lookback_bars must be a positive integer")
        last = await self.get_last_price(figi)
        if last is None or last.price is None or last.price <= 0:
            raise MarketDataUnavailable(f"no usable last price for {figi}")
        now = datetime.now(UTC)
        # One extra bar of width so the currently forming candle is included.
        window = timedelta(seconds=_TIMEFRAME_SECONDS[timeframe] * (lookback_bars + 1))
        candles = await self.get_candles(figi, timeframe, now - window, now)
        if not candles:
            raise MarketDataUnavailable(
                f"no candle history for {figi} @ {timeframe.value}"
            )
        return MarketSnapshot(
            figi=figi,
            timeframe=timeframe,
            timestamp=last.timestamp or candles[-1].timestamp,
            last_price=last.price,
            candles=tuple(candles),
        )

    @staticmethod
    def _split_range(
        from_: datetime, to: datetime, chunk_seconds: int
    ) -> list[tuple[datetime, datetime]]:
        """Split [from_, to] into consecutive chunks of at most chunk_seconds."""
        from_ = _as_utc(from_)
        to = _as_utc(to)
        chunk = timedelta(seconds=chunk_seconds)
        start = from_
        chunks: list[tuple[datetime, datetime]] = []
        while start < to:
            end = min(start + chunk, to)
            chunks.append((start, end))
            start = end
        return chunks

    @staticmethod
    def _sort_and_dedupe(candles: list[Candle]) -> list[Candle]:
        """Sort by timestamp and remove exact duplicate timestamps."""
        unique: dict[datetime, Candle] = {}
        for candle in candles:
            unique[candle.timestamp] = candle
        return [unique[key] for key in sorted(unique)]

    async def persist_candles(self, session, candles: list[Candle]) -> int:
        """Persist candles into PostgreSQL (optional; unique (figi, tf, ts))."""
        from app.models.market_candle import MarketCandle

        count = 0
        for candle in candles:
            session.add(
                MarketCandle(
                    figi=candle.figi,
                    timeframe=candle.timeframe.value,
                    timestamp=candle.timestamp,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    is_complete=candle.is_complete,
                )
            )
            count += 1
        await session.commit()
        return count


def _as_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
