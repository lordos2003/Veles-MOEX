"""Broker-neutral live MarketContext / MarketSnapshot boundary (MVP-6.8/6.10).

A StrategyEngine ``MarketContext`` must be built from real broker-neutral market
data. This module provides the production integration that constructs a
MarketContext for a running bot from the existing broker-neutral market-data
service: a last-price-only context (MVP-6.8) or a full market snapshot built
from the bot's own configured timeframe (MVP-6.10). It never fabricates
prices, candles or timestamps: a missing or non-usable live value raises
|MarketContextUnavailable| / |MarketDataUnavailable| instead.

The per-bot timeframe originates from the bot's own strategy configuration
(``StrategyConfig.timeframe``); no global runtime timeframe or implicit
production default exists. A missing timeframe raises
|TimeframeNotConfigured| and blocks the live processing cycle explicitly; an
invalid timeframe fails strategy configuration validation at load time
(StrategyLoadError).

The snapshot candle-history length is a separate, explicitly configured
project-level parameter (``StrategyConfig.lookback_bars``). The official
Veles documentation does not define a universal warmup/history/lookback rule,
so no lookback is derived from indicator periods/shifts or any other Veles
semantic. A missing lookback raises |LookbackNotConfigured| and blocks the
live processing cycle explicitly; a non-positive value fails strategy
configuration validation at load time (StrategyLoadError).
"""

from __future__ import annotations

from app.domain.marketdata import MarketSnapshot
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import StrategyConfig
from app.strategies.domain import MarketContext


class MarketContextUnavailable(RuntimeError):
    """Raised when a live MarketContext cannot be built from broker data."""


class TimeframeNotConfigured(RuntimeError):
    """Raised when a live strategy cycle has no valid per-bot timeframe.

    The live path never falls back to a global or implicit default timeframe:
    the cycle is blocked explicitly.
    """


class LookbackNotConfigured(RuntimeError):
    """Raised when a live strategy cycle has no explicitly configured lookback.

    The snapshot candle-history length is an explicit project-level contract
    parameter (``StrategyConfig.lookback_bars``); no lookback is inferred from
    indicator periods/shifts or any other Veles semantic. The live path never
    substitutes a default: the cycle is blocked explicitly.
    """


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


def market_snapshot_to_context(snapshot: MarketSnapshot) -> MarketContext:
    """Convert a broker-neutral MarketSnapshot into a Strategy MarketContext.

    The snapshot's candles become the bot-timeframe bar series of the context;
    the last price and the snapshot timestamp are preserved. No values are
    invented: an empty snapshot yields an empty series (not fabricated bars).
    """
    series = BarSeries(
        timeframe=snapshot.timeframe,
        bars=[
            Bar(
                timestamp=candle.timestamp,
                open=float(candle.open),
                high=float(candle.high),
                low=float(candle.low),
                close=float(candle.close),
                volume=float(candle.volume),
                is_complete=(
                    True if candle.is_complete is None else candle.is_complete
                ),
            )
            for candle in snapshot.candles
        ],
    )
    return MarketContext(
        price=float(snapshot.last_price),
        timestamp=snapshot.timestamp,
        snapshot=Snapshot(series={snapshot.timeframe: series}),
    )


async def build_market_snapshot_context(
    market_data,
    instrument_figi: str,
    strategy_config: StrategyConfig,
) -> MarketContext:
    """Build the live MarketContext for one bot's strategy cycle (MVP-6.10).

    The per-bot timeframe and the explicitly configured snapshot lookback
    (``StrategyConfig.lookback_bars``) originate from the bot's own strategy
    configuration; no global/implicit defaults exist and no lookback is
    derived from indicator semantics. ``market_data`` is any broker-neutral
    provider exposing ``get_snapshot(figi, timeframe, lookback_bars)`` (e.g.
    the existing ``MarketDataService``), so this boundary stays broker-neutral.

    Raises |TimeframeNotConfigured| when the per-bot timeframe is missing,
    |LookbackNotConfigured| when no explicit lookback is configured, and
    |MarketDataUnavailable| when no usable live market data exists; no
    synthetic market data is ever substituted.
    """
    timeframe = strategy_config.timeframe
    if timeframe is None:
        raise TimeframeNotConfigured(
            f"no per-bot timeframe configured for {instrument_figi}; the live "
            "strategy cycle is blocked (no implicit default timeframe)"
        )
    lookback_bars = strategy_config.lookback_bars
    if lookback_bars is None:
        raise LookbackNotConfigured(
            f"no explicit snapshot lookback configured for {instrument_figi}; "
            "the live strategy cycle is blocked (no lookback is inferred from "
            "indicator periods/shifts)"
        )
    snapshot = await market_data.get_snapshot(
        instrument_figi, timeframe, lookback_bars
    )
    return market_snapshot_to_context(snapshot)
