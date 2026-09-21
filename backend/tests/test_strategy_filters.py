"""Tests for Veles-style Filters / Signals evaluation (Strategy Engine MVP-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.marketdata import Timeframe
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.filters import (
    CalculationMethod,
    CandleSpec,
    ConstantValue,
    FilterCondition,
    FilterEvaluator,
    FilterGroup,
    IndicatorSpec,
    Operator,
)

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
EV = FilterEvaluator()


def _bar(ts, close, *, complete=True, high=None, low=None):
    high = close if high is None else high
    low = close if low is None else low
    return Bar(
        timestamp=ts, open=low, high=high, low=low, close=close, volume=1.0, is_complete=complete
    )


def _series(timeframe, bars):
    return BarSeries(timeframe=timeframe, bars=bars)


def _snap(*series):
    return Snapshot(series={s.timeframe: s for s in series})


def _min_series(closes, *, complete_last=True):
    bars = [
        _bar(
            T0 + timedelta(minutes=i),
            c,
            complete=(complete_last or i < len(closes) - 1),
        )
        for i, c in enumerate(closes)
    ]
    return _series(Timeframe.MIN_5, bars)


def _close_cond(op, threshold, tf=Timeframe.MIN_5, shift=0):
    return FilterCondition(
        arg1=CandleSpec(timeframe=tf, series="close", shift=shift),
        operator=op,
        arg2=ConstantValue(value=threshold),
    )


def _ind_cond(
    name, op, threshold, tf=Timeframe.MIN_5, period=None, series_name="value", params=None
):
    return FilterCondition(
        arg1=IndicatorSpec(
            name=name, timeframe=tf, period=period, series=series_name, params=params or {}
        ),
        operator=op,
        arg2=ConstantValue(value=threshold),
    )


def _result(groups, closes, minutes, *, method=CalculationMethod.AT_BAR_CLOSE, complete_last=True):
    return EV.evaluate(
        groups,
        method,
        _snap(_min_series(closes, complete_last=complete_last)),
        T0 + timedelta(minutes=minutes),
    )


def test_greater_than_state():
    groups = [FilterGroup(conditions=[_close_cond(Operator.GREATER_THAN, 100)])]
    assert _result(groups, [90, 95, 105, 97], 2) is True
    assert _result(groups, [90, 95, 105, 97], 3) is False


def test_less_than_state():
    groups = [FilterGroup(conditions=[_close_cond(Operator.LESS_THAN, 100)])]
    assert _result(groups, [90, 95, 105, 97], 0) is True
    assert _result(groups, [90, 95, 105, 97], 2) is False


def test_crossing_upward_event():
    groups = [FilterGroup(conditions=[_close_cond(Operator.CROSS_UP, 100)])]
    assert _result(groups, [95, 98, 101, 103], 2) is True
    assert _result(groups, [95, 98, 101, 103], 3) is False


def test_crossing_downward_event():
    groups = [FilterGroup(conditions=[_close_cond(Operator.CROSS_DOWN, 100)])]
    assert _result(groups, [105, 102, 98, 95], 2) is True
    assert _result(groups, [105, 102, 98, 95], 3) is False


def test_and_inside_group():
    groups = [FilterGroup(conditions=[
        _close_cond(Operator.GREATER_THAN, 100),
        _close_cond(Operator.GREATER_THAN, 101),
    ])]
    assert _result(groups, [90, 95, 105, 97], 2) is True
    assert _result(groups, [90, 95, 105, 97], 3) is False


def test_or_between_groups():
    groups = [
        FilterGroup(conditions=[_close_cond(Operator.GREATER_THAN, 100)]),
        FilterGroup(conditions=[_close_cond(Operator.LESS_THAN, 90)]),
    ]
    assert _result(groups, [80, 95, 105, 97], 0) is True
    assert _result(groups, [80, 95, 105, 97], 2) is True
    assert _result(groups, [80, 95, 105, 97], 3) is False


def test_nested_and_or_combination():
    groups = [
        FilterGroup(conditions=[
            _close_cond(Operator.GREATER_THAN, 100),
            _close_cond(Operator.LESS_THAN, 110),
        ]),
        FilterGroup(conditions=[_close_cond(Operator.LESS_THAN, 90)]),
    ]
    assert _result(groups, [80, 95, 105, 115], 2) is True
    assert _result(groups, [80, 95, 105, 115], 3) is False


def test_bar_close_timing_ignores_forming_bar():
    groups = [FilterGroup(conditions=[_close_cond(Operator.GREATER_THAN, 97)])]
    assert _result(groups, [95, 96, 99], 2, complete_last=False) is False


def test_per_minute_timing_uses_forming_bar():
    groups = [FilterGroup(conditions=[_close_cond(Operator.GREATER_THAN, 97)])]
    assert _result(
        groups,
        [95, 96, 99],
        2,
        method=CalculationMethod.PER_MINUTE,
        complete_last=False,
    ) is True


def test_higher_timeframe_signal_active_with_lower_condition():
    h1 = _series(Timeframe.HOUR_1, [
        _bar(T0, 10),
        _bar(T0 + timedelta(hours=1), 11),
        _bar(T0 + timedelta(hours=2), 12),
    ])
    m1 = _series(Timeframe.MIN_1, [
        _bar(T0 + timedelta(hours=2, minutes=0), 6),
        _bar(T0 + timedelta(hours=2, minutes=1), 7),
    ])
    groups = [FilterGroup(conditions=[
        _ind_cond("RSI", Operator.GREATER_THAN, 50, tf=Timeframe.HOUR_1, period=2),
        _close_cond(Operator.GREATER_THAN, 5, tf=Timeframe.MIN_1),
    ])]
    snap = _snap(h1, m1)
    assert EV.evaluate(
        groups, CalculationMethod.AT_BAR_CLOSE, snap, T0 + timedelta(hours=2, minutes=0)
    ) is True
    assert EV.evaluate(
        groups, CalculationMethod.AT_BAR_CLOSE, snap, T0 + timedelta(hours=2, minutes=1)
    ) is True


def test_indicator_config_timeframe_period_shift():
    groups = [FilterGroup(conditions=[_ind_cond("RSI", Operator.GREATER_THAN, 50, period=2)])]
    assert _result(groups, [10, 11, 12, 13], 3) is True

    groups_p3 = [FilterGroup(conditions=[_ind_cond("RSI", Operator.GREATER_THAN, 50, period=3)])]
    series = _min_series([10, 11, 12, 13])
    assert EV.evaluate(
        groups_p3, CalculationMethod.AT_BAR_CLOSE, _snap(series), T0 + timedelta(minutes=3)
    ) is True

    shift_cond = _close_cond(Operator.GREATER_THAN, 100, shift=1)
    assert _result([FilterGroup(conditions=[shift_cond])], [95, 96, 105], 2) is False
    no_shift_cond = _close_cond(Operator.GREATER_THAN, 100)
    assert _result([FilterGroup(conditions=[no_shift_cond])], [95, 96, 105], 2) is True
