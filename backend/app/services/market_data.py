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
from app.domain.marketdata import Candle, LastPrice, Timeframe

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
