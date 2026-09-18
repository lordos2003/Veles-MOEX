"""Strategy Engine package."""

from __future__ import annotations

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

__all__ = [
    "BreakEvenConfig",
    "DCAGridConfig",
    "DCAGridEngine",
    "Direction",
    "EntryConfig",
    "EntryEngine",
    "EntrySignal",
    "ExitConfig",
    "ExitEngine",
    "ExitPlan",
    "FixedPercentageTP",
    "GridOrder",
    "MarketContext",
    "MultiTakeTP",
    "Plan",
    "RiskConfig",
    "SignalTP",
    "StopLossConfig",
    "StrategyConfig",
    "StrategyEngine",
    "TakeItem",
    "TPConfig",
    "TrailingTP",
]
