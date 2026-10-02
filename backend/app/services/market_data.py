"""Market data service.

Internal interface through which Strategy/Backtest/Trading engines request
market data. It depends only on the BrokerAdapter and the domain DTOs, so those
engines never touch a broker SDK. Handles timeframe conversion, chunking of long
ranges, merging, sorting and de-duplication of candles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.brokers.base import BrokerAdapter
from app.brokers.tinvest_errors import (
    InstrumentNotFoundError,
    InvalidRequestError,
    ResourceNotFoundError,
)
from app.core.config import Settings, get_settings
from app.domain.marketdata import (
    Candle,
    LastPrice,
    MarketDataUnavailable,
    MarketSnapshot,
    NoTradesInWindow,
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

_SECONDS_PER_DAY = 86400


class Clock(Protocol):
    """Injectable time source (MVP-6.15): deterministic snapshot tests."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production clock: current UTC time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class MarketDataService:
    """Provides normalized market data from a broker adapter."""

    def __init__(
        self,
        broker: BrokerAdapter,
        settings: Settings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._broker = broker
        self._settings = settings if settings is not None else get_settings()
        self._clock = clock if clock is not None else SystemClock()

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
        the most recent ``lookback_bars`` candles that actually exist at the
        broker for the instrument and timeframe. No synthetic value is
        substituted: a missing or non-positive last price raises
        |MarketDataUnavailable| instead.

        MVP-6.15 (L1–L4): the newest ``lookback_bars`` existing candles are
        returned regardless of trading breaks. The first request uses the
        MVP-6.10 wall-clock window ``(lookback_bars + 1) x timeframe``; when it
        does not contain enough candles (night/weekend/holiday gap), the search
        is extended backwards over disjoint windows of ``_TIMEFRAME_CHUNK_SECONDS``
        up to the configured depth until ``lookback_bars`` candles are collected
        or the depth is exhausted (L2). Less history than ``lookback_bars`` is
        returned as-is (L3); no candles at all over the whole depth raises
        |NoTradesInWindow| whose ``window_start`` is the depth start (L4).
        """
        if timeframe not in _SUPPORTED:
            raise InvalidRequestError(f"Unsupported timeframe: {timeframe}")
        if lookback_bars is None or lookback_bars < 1:
            raise InvalidRequestError("lookback_bars must be a positive integer")
        last = await self.get_last_price(figi)
        if last is None or last.price is None or last.price <= 0:
            raise MarketDataUnavailable(f"no usable last price for {figi}")
        now = self._clock.now()
        # One extra bar of width so the currently forming candle is included.
        window = timedelta(seconds=_TIMEFRAME_SECONDS[timeframe] * (lookback_bars + 1))
        window_start = now - window
        # L2: the maximum search depth backwards from "now" (ops parameters).
        depth = timedelta(
            seconds=max(
                self._settings.snapshot_min_search_days * _SECONDS_PER_DAY,
                self._settings.snapshot_search_factor
                * lookback_bars
                * _TIMEFRAME_SECONDS[timeframe],
            )
        )
        depth_start = now - depth
        candles = await self.get_candles(figi, timeframe, window_start, now)
        if len(candles) < lookback_bars:
            candles = await self._fill_backwards(
                figi, timeframe, candles, window_start, depth_start, lookback_bars
            )
        if not candles:
            # MVP-6.14 (N2): an empty result is not just "unavailable" — the
            # broker facts (last-trade time, search-depth start) travel with
            # the error so the scheduler can decide whether the window is
            # proven to contain no trades. A subclass keeps every existing
            # MarketDataUnavailable handler unchanged. (MVP-6.15 L4: the window
            # is the whole searched depth, not the initial wall-clock window.)
            raise NoTradesInWindow(
                f"no candle history for {figi} @ {timeframe.value}",
                last_trade_at=last.timestamp,
                window_start=depth_start,
            )
        # MVP-6.10 contract / Issue #3 (C7): the snapshot must contain exactly
        # the newest ``lookback_bars`` candles. The request window is wider
        # (lookback_bars + 1) so the forming candle is included, but the
        # snapshot itself is trimmed strictly to the contract: newest candles
        # kept, chronological order preserved.
        candles = candles[-lookback_bars:]
        return MarketSnapshot(
            figi=figi,
            timeframe=timeframe,
            timestamp=last.timestamp or candles[-1].timestamp,
            last_price=last.price,
            candles=tuple(candles),
            last_trade_at=last.timestamp,
        )

    async def _fill_backwards(
        self,
        figi: str,
        timeframe: Timeframe,
        candles: list[Candle],
        window_start: datetime,
        depth_start: datetime,
        lookback_bars: int,
    ) -> list[Candle]:
        """MVP-6.15 (L2): extend the candle search backwards to the depth.

        Walks backwards from the initial window with disjoint windows of at
        most ``_TIMEFRAME_CHUNK_SECONDS`` (the provider's per-request maximum,
        so each call is a single broker request), collecting candles until
        ``lookback_bars`` are gathered or the depth start is reached. Already
        requested ranges are never re-requested.
        """
        chunk_seconds = _TIMEFRAME_CHUNK_SECONDS[timeframe]
        cursor = window_start
        while len(candles) < lookback_bars and cursor > depth_start:
            chunk_from = max(depth_start, cursor - timedelta(seconds=chunk_seconds))
            more = await self.get_candles(figi, timeframe, chunk_from, cursor)
            if more:
                candles = self._sort_and_dedupe(more + candles)
            cursor = chunk_from
        return candles

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
