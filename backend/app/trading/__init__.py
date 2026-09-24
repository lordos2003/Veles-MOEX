"""Trading Engine package."""

from __future__ import annotations

from app.trading.bot_lifecycle import (
    BotRuntime,
    BotRuntimeManager,
    BotStartRejected,
    BotStateError,
)
from app.trading.domain import (
    ALLOWED_TRANSITIONS,
    ExecutionIntent,
    Fill,
    InternalOrder,
    OrderState,
    OrderUpdate,
    PositionUpdate,
    TradeFill,
    can_transition,
)
from app.trading.engine import TradingEngine, compose_strategy_engine
from app.trading.live_execution import LiveExecutionBlocked, LiveExecutionService
from app.trading.market_context import MarketContextUnavailable, build_market_context
from app.trading.order_manager import OrderManager, OrderStateError
from app.trading.plan_intent import plan_to_intents
from app.trading.position_manager import (
    InvalidPositionQuantity,
    Position,
    PositionManager,
    PositionUnavailable,
)
from app.trading.recovery import LiveRecoveryCoordinator, RecoveryResult, RecoveryStatus
from app.trading.repository import (
    InMemoryFillRepository,
    InMemoryIntentRepository,
    InMemoryOrderRepository,
    InMemoryPositionRepository,
)
from app.trading.risk_manager import RiskLimits, RiskManager, RiskRejected
from app.trading.sizing import PositionSizing, SizingNotConfigured
from app.trading.state import InMemoryLiveStateStore, LiveStateSnapshot, LiveStateStore

__all__ = [
    "ALLOWED_TRANSITIONS",
    "BotRuntime",
    "BotRuntimeManager",
    "BotStateError",
    "BotStartRejected",
    "ExecutionIntent",
    "Fill",
    "InMemoryFillRepository",
    "InMemoryIntentRepository",
    "InMemoryLiveStateStore",
    "InMemoryOrderRepository",
    "InMemoryPositionRepository",
    "InternalOrder",
    "InvalidPositionQuantity",
    "LiveExecutionBlocked",
    "LiveExecutionService",
    "LiveRecoveryCoordinator",
    "LiveStateSnapshot",
    "LiveStateStore",
    "MarketContextUnavailable",
    "OrderManager",
    "OrderState",
    "OrderStateError",
    "OrderUpdate",
    "Position",
    "PositionManager",
    "PositionSizing",
    "PositionUnavailable",
    "PositionUpdate",
    "RecoveryResult",
    "RecoveryStatus",
    "RiskManager",
    "RiskRejected",
    "RiskLimits",
    "SizingNotConfigured",
    "TradeFill",
    "TradingEngine",
    "build_market_context",
    "can_transition",
    "compose_strategy_engine",
    "plan_to_intents",
]
