"""Market data domain models (broker-agnostic, Decimal prices, UTC timestamps)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class Timeframe(StrEnum):
    """Internal timeframe. Independent from any broker's interval enum."""

    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1mo"


@dataclass(frozen=True)
class Candle:
    """An OHLCV candle for a single instrument and timeframe."""

    figi: str
    timeframe: Timeframe
    timestamp: datetime  # timezone-aware UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    is_complete: bool | None = None


@dataclass(frozen=True)
class LastPrice:
    """The last trade price for an instrument."""

    figi: str
    price: Decimal
    timestamp: datetime | None = None
    ticker: str | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    """A broker-neutral live market snapshot for one instrument/timeframe.

    Assembled exclusively from real broker data: the instrument identity
    (FIGI), the timeframe, the snapshot timestamp (timezone-aware UTC), the
    last trade price (``Decimal``) and the recent candle history. No value is
    fabricated; a snapshot without a usable price/history is not produced
    (see ``MarketDataUnavailable``).
    """

    figi: str
    timeframe: Timeframe
    timestamp: datetime  # timezone-aware UTC
    last_price: Decimal
    candles: tuple[Candle, ...] = ()


class MarketDataUnavailable(RuntimeError):
    """Raised when a live market snapshot cannot be assembled from broker data.

    Broker-neutral domain error: a missing or non-positive last price, or an
    empty candle history, blocks the live processing cycle instead of being
    replaced by a synthetic value.
    """
