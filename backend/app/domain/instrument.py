"""Instrument domain enums.

These are our internal, broker-agnostic types. T-Invest-specific values are
converted inside the broker adapter and never leak into the domain/API layer.
"""

from __future__ import annotations

from enum import StrEnum


class InstrumentType(StrEnum):
    """Canonical instrument types supported by the platform."""

    SHARE = "SHARE"
    BOND = "BOND"
    ETF = "ETF"
    FUTURE = "FUTURE"
    CURRENCY = "CURRENCY"


class TradingStatus(StrEnum):
    """Normalized trading status for an instrument."""

    TRADING_AVAILABLE = "TRADING_AVAILABLE"
    TRADING_UNAVAILABLE = "TRADING_UNAVAILABLE"
