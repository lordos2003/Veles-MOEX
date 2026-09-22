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
from app.trading.order_manager import OrderManager, OrderStateError
from app.trading.position_manager import Position, PositionManager
from app.trading.repository import (
    InMemoryFillRepository,
    InMemoryIntentRepository,
    InMemoryOrderRepository,
)
from app.trading.risk_manager import RiskManager

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ExecutionIntent",
    "Fill",
    "InMemoryFillRepository",
    "InMemoryIntentRepository",
    "InMemoryOrderRepository",
    "InternalOrder",
    "OrderManager",
    "OrderState",
    "OrderStateError",
    "OrderUpdate",
    "Position",
    "PositionManager",
    "PositionUpdate",
    "RiskManager",
    "TradeFill",
    "TradingEngine",
    "can_transition",
]
