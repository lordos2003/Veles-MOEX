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
