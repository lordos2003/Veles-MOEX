"""Trading Engine package."""

from __future__ import annotations

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
from app.trading.engine import TradingEngine
from app.trading.live_execution import LiveExecutionBlocked, LiveExecutionService
from app.trading.order_manager import OrderManager, OrderStateError
from app.trading.position_manager import Position, PositionManager
from app.trading.recovery import LiveRecoveryCoordinator, RecoveryResult, RecoveryStatus
from app.trading.repository import (
    InMemoryFillRepository,
    InMemoryIntentRepository,
    InMemoryOrderRepository,
    InMemoryPositionRepository,
)
from app.trading.risk_manager import RiskLimits, RiskManager, RiskRejected
from app.trading.state import InMemoryLiveStateStore, LiveStateSnapshot, LiveStateStore

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ExecutionIntent",
    "Fill",
    "InMemoryFillRepository",
    "InMemoryIntentRepository",
    "InMemoryLiveStateStore",
    "InMemoryOrderRepository",
    "InMemoryPositionRepository",
    "InternalOrder",
    "LiveExecutionBlocked",
    "LiveExecutionService",
    "LiveRecoveryCoordinator",
    "LiveStateSnapshot",
    "LiveStateStore",
    "OrderManager",
    "OrderState",
    "OrderStateError",
    "OrderUpdate",
    "Position",
    "PositionManager",
    "PositionUpdate",
    "RecoveryResult",
    "RecoveryStatus",
    "RiskManager",
    "RiskRejected",
    "RiskLimits",
    "TradeFill",
    "TradingEngine",
    "can_transition",
]
