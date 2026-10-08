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

The snapshot candle-history length comes from contract H1 (owner decision
2026-10-08, MVP-7.5 U10): an explicit ``StrategyConfig.lookback_bars`` takes
priority; otherwise the engine computes the depth from the strategy's filter
arguments (``computed_lookback_bars``). ``LookbackNotConfigured`` is retained
for compatibility but no longer raised. A non-positive explicit value fails
strategy configuration validation at load time (StrategyLoadError).
"""

from __future__ import annotations

from app.domain.marketdata import MarketSnapshot
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import StrategyConfig, iter_filter_groups
from app.strategies.domain import MarketContext
from app.strategies.filters import CandleSpec, IndicatorSpec


class MarketContextUnavailable(RuntimeError):
    """Raised when a live MarketContext cannot be built from broker data."""


class TimeframeNotConfigured(RuntimeError):
    """Raised when a live strategy cycle has no valid per-bot timeframe.

    The live path never falls back to a global or implicit default timeframe:
    the cycle is blocked explicitly.
    """


class LookbackNotConfigured(RuntimeError):
    """Raised when a live strategy cycle has no snapshot lookback at all.

    Deprecated since MVP-7.5 U10 (contract H1): the engine computes the depth
    from the strategy's filter arguments, so a config always has a resolved
    lookback. The class is kept for imports/tests compatibility.
    """


# Contract H1 (owner decision 2026-10-08): recursive indicators depend on the
# whole history, so their weight is 5x the period. MACD has no period: the base
# is the largest of its fast/slow/signal EMA periods.
_RECURSIVE_INDICATORS = frozenset({"EMA", "RSI", "ATR", "MACD"})


def _indicator_weight(spec: IndicatorSpec) -> int:
    """H1 contract: ``W_i`` for one indicator argument."""
    if spec.name in _RECURSIVE_INDICATORS:
        if spec.name == "MACD":
            periods = [
                int(spec.params[p])
                for p in ("fast", "slow", "signal")
                if p in spec.params and spec.params[p] is not None
            ]
            base = max(periods) if periods else 1
            return 5 * base
        return 5 * (spec.period if spec.period is not None else 1)
    return spec.period if spec.period is not None else 1


def _argument_depth(arg: IndicatorSpec | CandleSpec) -> int:
    """H1 contract: ``W_i + shift_i`` for one filter argument.

    Constants carry no history need and are skipped by the caller.
    """
    if isinstance(arg, CandleSpec):
        return 1 + arg.shift
    return _indicator_weight(arg) + arg.shift


def computed_lookback_bars(config: StrategyConfig) -> int:
    """Contract H1: computed snapshot history depth in bars.

    ``N = max_i(W_i + shift_i) + 1`` over every indicator and candle argument
    of all conditions the strategy evaluates (entry, grid signal groups, signal
    take-profit, signal stop-loss); ``+1`` is the forming bar. A strategy
    without any argument yields ``N = 1``.
    """
    depth = 0
    for group in iter_filter_groups(config):
        for cond in group.conditions:
            for arg in (cond.arg1, cond.arg2):
                if isinstance(arg, (IndicatorSpec, CandleSpec)):
                    depth = max(depth, _argument_depth(arg))
    return depth + 1


def resolved_lookback_bars(config: StrategyConfig) -> int:
    """The snapshot history the live cycle must load (H1).

    An explicit ``StrategyConfig.lookback_bars`` (old strategies keep it and it
    stays editable in JSON) takes priority over the computed depth.
    """
    if config.lookback_bars is not None:
        return config.lookback_bars
    return computed_lookback_bars(config)


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

    The per-bot timeframe originates from the bot's own strategy configuration
    (``StrategyConfig.timeframe``); no global/implicit defaults exist. The
    snapshot history length is resolved by contract H1: an explicit
    ``StrategyConfig.lookback_bars`` takes priority, otherwise the engine
    computes the depth from the strategy's filter arguments
    (``resolved_lookback_bars``). ``market_data`` is any broker-neutral
    provider exposing ``get_snapshot(figi, timeframe, lookback_bars)`` (e.g.
    the existing ``MarketDataService``), so this boundary stays broker-neutral.

    Raises |TimeframeNotConfigured| when the per-bot timeframe is missing and
    |MarketDataUnavailable| when no usable live market data exists; no
    synthetic market data is ever substituted.
    """
    timeframe = strategy_config.timeframe
    if timeframe is None:
        raise TimeframeNotConfigured(
            f"no per-bot timeframe configured for {instrument_figi}; the live "
            "strategy cycle is blocked (no implicit default timeframe)"
        )
    lookback = resolved_lookback_bars(strategy_config)
    snapshot = await market_data.get_snapshot(
        instrument_figi, timeframe, lookback
    )
    return market_snapshot_to_context(snapshot)
