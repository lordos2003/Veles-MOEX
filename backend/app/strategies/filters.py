"""Veles-style Filters / Signals for the Strategy Engine.

A strategy entry is a set of filter *groups*. Conditions inside a group are
combined with AND; groups are combined with OR. Each condition is
Argument1 + Operator + Argument2.

Operators:
- ``>`` / ``<``: a *state* that stays true while the relation holds.
- crossing upward / downward: an *event* at the bar where the relation flips.

Arguments can be an indicator, a candle field, or a constant. Each argument
carries its own timeframe, so higher-timeframe signals stay active across the
lower-timeframe candles (multi-timeframe active-signal state).

Calculation methods:
- AT_BAR_CLOSE — evaluate on the last closed bar.
- PER_MINUTE — evaluate on the current (possibly forming) bar.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.domain.marketdata import Timeframe
from app.strategies.bars import Snapshot
from app.strategies.indicators import indicator_series


class Operator(StrEnum):
    GREATER_THAN = ">"
    LESS_THAN = "<"
    CROSS_UP = "cross_up"
    CROSS_DOWN = "cross_down"


class CalculationMethod(StrEnum):
    AT_BAR_CLOSE = "at_bar_close"
    PER_MINUTE = "per_minute"


class ConstantValue(BaseModel):
    kind: Literal["constant"] = "constant"
    value: float


class IndicatorSpec(BaseModel):
    kind: Literal["indicator"] = "indicator"
    name: str
    timeframe: Timeframe
    period: int | None = None
    method: str | None = None
    # Shift: number of bars to look back (0 = current).
    shift: int = 0
    # Which output series the indicator exposes (e.g. MACD/histogram, BB upper).
    series: str = "value"
    params: dict[str, Any] = Field(default_factory=dict)


class CandleSpec(BaseModel):
    kind: Literal["candle"] = "candle"
    timeframe: Timeframe
    series: Literal["open", "high", "low", "close", "volume"] = "close"
    shift: int = 0


Argument = Annotated[ConstantValue | IndicatorSpec | CandleSpec, Field(discriminator="kind")]


class FilterCondition(BaseModel):
    arg1: Argument
    operator: Operator
    arg2: Argument


class FilterGroup(BaseModel):
    conditions: list[FilterCondition] = Field(default_factory=list)


class FilterEvaluator:
    """Evaluates entry filter groups against a market snapshot."""

    def evaluate(
        self,
        entry_groups: list[FilterGroup],
        method: CalculationMethod,
        snapshot: Snapshot,
        now: datetime,
    ) -> bool:
        if not entry_groups:
            # No entry conditions -> unconditional entry.
            return True
        return any(
            all(self._condition(c, method, snapshot, now) for c in group.conditions)
            for group in entry_groups
        )

    def _condition(
        self,
        cond: FilterCondition,
        method: CalculationMethod,
        snapshot: Snapshot,
        now: datetime,
    ) -> bool:
        v1, p1 = self._arg_values(cond.arg1, method, snapshot, now)
        v2, p2 = self._arg_values(cond.arg2, method, snapshot, now)
        if v1 is None or v2 is None:
            return False
        op = cond.operator
        if op == Operator.GREATER_THAN:
            return v1 > v2
        if op == Operator.LESS_THAN:
            return v1 < v2
        if op == Operator.CROSS_UP:
            return p1 is not None and p2 is not None and p1 <= p2 and v1 > v2
        if op == Operator.CROSS_DOWN:
            return p1 is not None and p2 is not None and p1 >= p2 and v1 < v2
        return False

    def _arg_values(
        self, arg: Argument, method: CalculationMethod, snapshot: Snapshot, now: datetime
    ) -> tuple[float | None, float | None]:
        if isinstance(arg, ConstantValue):
            return arg.value, arg.value
        series = snapshot.get(arg.timeframe)
        if series is None:
            return None, None
        idx = self._current_index(series, now, method)
        if idx is None:
            return None, None
        if arg.shift:
            idx -= arg.shift
            if idx < 0:
                return None, None
        value = self._value_at(arg, series, idx)
        prev = self._value_at(arg, series, idx - 1) if idx > 0 else None
        return value, prev

    @staticmethod
    def _current_index(series, now: datetime, method: CalculationMethod) -> int | None:
        last = -1
        for i, bar in enumerate(series.bars):
            if bar.timestamp <= now:
                last = i
            else:
                break
        if last < 0:
            return None
        if method == CalculationMethod.AT_BAR_CLOSE and not series.bars[last].is_complete:
            last -= 1
            if last < 0:
                return None
        return last

    @staticmethod
    def _value_at(arg: Argument, series, idx: int) -> float | None:
        if isinstance(arg, IndicatorSpec):
            values = indicator_series(arg.name, series, arg.period, arg.series, arg.params)
            if 0 <= idx < len(values):
                return values[idx]
            return None
        if isinstance(arg, CandleSpec):
            values = series.attr(arg.series)
            if 0 <= idx < len(values):
                return values[idx]
            return None
        return None
