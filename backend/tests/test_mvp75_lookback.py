"""MVP-7.5 U10: contract H1 — computed snapshot history depth.

N = max_i(W_i + shift_i) + 1 over every indicator/candle argument of the
conditions the strategy evaluates (entry, grid signal groups, signal TP,
signal stop-loss):

- W = 5 x period for recursive indicators (EMA, RSI, ATR; MACD — 5 x max of
  fast/slow/signal);
- W = period for the other period indicators (SMA, Bollinger, CCI, ...);
- candle without period: W = 1;
- a strategy without arguments: N = 1;
- an explicit ``lookback_bars`` takes priority over the computed depth.

Deterministic and broker-neutral: pure StrategyConfig math, no network.
"""

from __future__ import annotations

from app.domain.marketdata import Timeframe
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.filters import (
    CandleSpec,
    ConstantValue,
    FilterCondition,
    FilterGroup,
    IndicatorSpec,
    Operator,
)
from app.trading.market_context import computed_lookback_bars, resolved_lookback_bars

TF = Timeframe.MIN_5


def _indicator(
    name: str, period: int | None = None, shift: int = 0, params: dict | None = None
) -> IndicatorSpec:
    return IndicatorSpec(
        kind="indicator", name=name, timeframe=TF, period=period, shift=shift,
        params=params or {},
    )


def _candle(shift: int = 0) -> CandleSpec:
    return CandleSpec(kind="candle", timeframe=TF, series="close", shift=shift)


def _config(*groups: FilterGroup, **overrides) -> StrategyConfig:
    cfg = dict(
        direction=Direction.LONG,
        timeframe=TF,
        entry=EntryConfig(groups=list(groups)),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        dca_grid=DCAGridConfig(levels=1),
    )
    cfg.update(overrides)
    return StrategyConfig(**cfg)


def _group(*conditions: FilterCondition) -> FilterGroup:
    return FilterGroup(conditions=list(conditions))


def _cond(arg1, arg2=None, operator: Operator = Operator.GREATER_THAN) -> FilterCondition:
    if arg2 is None:
        arg2 = ConstantValue(kind="constant", value=0.0)
    return FilterCondition(arg1=arg1, operator=operator, arg2=arg2)


def test_h1_sma_weight_is_period() -> None:
    # W = period (non-recursive), shift 0, +1 forming bar.
    assert computed_lookback_bars(_config(_group(_cond(_indicator("SMA", period=20))))) == 21


def test_h1_recursive_indicators_use_five_times_period() -> None:
    for name, period in (("EMA", 9), ("RSI", 14), ("ATR", 14)):
        computed = computed_lookback_bars(
            _config(_group(_cond(_indicator(name, period=period))))
        )
        assert computed == 5 * period + 1, name


def test_h1_macd_uses_five_times_max_param_period() -> None:
    macd = _indicator("MACD", params={"fast": 12, "slow": 26, "signal": 9})
    # Base = 5 x max(12, 26, 9) = 130; N = 131.
    assert computed_lookback_bars(_config(_group(_cond(macd)))) == 131


def test_h1_candle_weight_is_one_plus_shift() -> None:
    assert computed_lookback_bars(_config(_group(_cond(_candle())))) == 2
    assert computed_lookback_bars(_config(_group(_cond(_candle(shift=3))))) == 5


def test_h1_multiple_conditions_take_maximum() -> None:
    config = _config(
        _group(
            _cond(_indicator("SMA", period=10, shift=2)),           # 10 + 2
            _cond(_candle(shift=7)),                                 # 1 + 7
        ),
        _group(
            _cond(_indicator("RSI", period=14)),                    # 5*14
        ),
    )
    # max(12, 8, 70) + 1
    assert computed_lookback_bars(config) == 71


def test_h1_shift_adds_to_weight() -> None:
    config = _config(_group(_cond(_indicator("EMA", period=9, shift=3))))
    assert computed_lookback_bars(config) == 5 * 9 + 3 + 1


def test_h1_strategy_without_arguments_yields_one() -> None:
    assert computed_lookback_bars(_config()) == 1


def test_h1_explicit_lookback_takes_priority_over_computed() -> None:
    config = _config(
        _group(_cond(_indicator("EMA", period=9, shift=3))),
        lookback_bars=7,
    )
    assert resolved_lookback_bars(config) == 7
    assert computed_lookback_bars(config) == 49  # the computation itself is untouched


def test_h1_computed_depth_used_when_lookback_is_missing() -> None:
    config = _config(_group(_cond(_indicator("RSI", period=14))))
    assert config.lookback_bars is None
    assert resolved_lookback_bars(config) == 71
