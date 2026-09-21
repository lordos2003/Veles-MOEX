"""Strategy Engine package."""

from __future__ import annotations

from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    BreakEvenConfig,
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    MultiTakeTP,
    RiskConfig,
    SignalTP,
    StopLossConfig,
    StrategyConfig,
    TakeItem,
    TPConfig,
    TrailingTP,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import EntrySignal, ExitPlan, GridOrder, MarketContext, Plan
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.strategies.filters import (
    Argument,
    CalculationMethod,
    CandleSpec,
    ConstantValue,
    FilterCondition,
    FilterEvaluator,
    FilterGroup,
    IndicatorSpec,
    Operator,
)
from app.strategies.indicators import indicator_series

__all__ = [
    "Argument",
    "Bar",
    "BarSeries",
    "BreakEvenConfig",
    "CalculationMethod",
    "CandleSpec",
    "ConstantValue",
    "DCAGridConfig",
    "DCAGridEngine",
    "Direction",
    "EntryConfig",
    "EntryEngine",
    "EntrySignal",
    "ExitConfig",
    "ExitEngine",
    "ExitPlan",
    "FilterCondition",
    "FilterEvaluator",
    "FilterGroup",
    "FixedPercentageTP",
    "GridOrder",
    "IndicatorSpec",
    "MarketContext",
    "MultiTakeTP",
    "Operator",
    "Plan",
    "RiskConfig",
    "SignalTP",
    "Snapshot",
    "StopLossConfig",
    "StrategyConfig",
    "StrategyEngine",
    "TakeItem",
    "TPConfig",
    "TrailingTP",
    "indicator_series",
]
