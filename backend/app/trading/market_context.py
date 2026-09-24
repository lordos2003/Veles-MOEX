"""Broker-neutral live MarketContext boundary (MVP-6.8).

A StrategyEngine ``MarketContext`` must be built from real broker-neutral market
data. This module provides the smallest production integration that constructs a
MarketContext for a running bot from the existing broker-neutral market-data
service. It never fabricates prices, candles or timestamps: a missing or
non-positive live price raises |MarketContextUnavailable| instead.

The candle/snapshot source (needed for the entry-filter evaluation) and the
per-bot timeframe are documented as not yet wired; this boundary supplies a
real last price and its timestamp only.
"""

from __future__ import annotations

from app.strategies.domain import MarketContext


class MarketContextUnavailable(RuntimeError):
    """Raised when a live MarketContext cannot be built from broker data."""


async def build_market_context(market_data, instrument_figi: str) -> MarketContext:
    """Build a MarketContext from the broker-neutral last trade price.

    ``market_data`` is any broker-neutral provider exposing
    ``get_last_price(figi)`` (e.g. the existing ``MarketDataService``), so this
    boundary stays broker-neutral. Raises |MarketContextUnavailable| when no
    usable live price is available; no synthetic value is substituted.
    """
    last = await market_data.get_last_price(instrument_figi)
    if last is None or last.price is None or last.price <= 0:
        raise MarketContextUnavailable(
            f"no usable live price for {instrument_figi}"
        )
    return MarketContext(price=float(last.price), timestamp=last.timestamp)
