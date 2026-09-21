"""Strategy Engine package."""

from __future__ import annotations

from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    BreakEvenConfig,
    CustomLevel,
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    MultiTakeTP,
    RiskConfig,
    SignalOffsetReference,
    SignalTP,
    StopLossConfig,
    StrategyConfig,
    TakeItem,
    TPConfig,
    TradingMode,
    TrailingTP,
)
from app.strategies.dca_grid import (
    DCAGridEngine,
    DCAOrder,
    GridLevel,
    GridOrderPlan,
    GridPriceDistribution,
    GridState,
    LevelStatus,
)
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
    "CustomLevel",
    "DCAGridConfig",
    "DCAGridEngine",
    "DCAOrder",
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
    "GridLevel",
    "GridOrder",
    "GridOrderPlan",
    "GridPriceDistribution",
    "GridState",
    "IndicatorSpec",
    "LevelStatus",
    "MarketContext",
    "MultiTakeTP",
    "Operator",
    "Plan",
    "RiskConfig",
    "SignalOffsetReference",
    "SignalTP",
    "Snapshot",
    "StopLossConfig",
    "StrategyConfig",
    "StrategyEngine",
    "TakeItem",
    "TPConfig",
    "TradingMode",
    "TrailingTP",
    "indicator_series",
]
