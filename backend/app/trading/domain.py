"""Broker-neutral live execution domain (MVP-6.1).

These models carry the execution intent, internal order, fills and events. They
must not depend on T-Invest (or any broker). The Order Manager / Position
Manager consume only these types plus the broker-neutral BrokerAdapter DTOs.

Money/quantity values use ``Decimal``; timestamps are timezone-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from app.models.enums import OrderSide, OrderType


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OrderState(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


# Explicit allowed lifecycle transitions. No free-for-all status assignment.
ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.CREATED: frozenset({OrderState.SUBMITTED, OrderState.REJECTED, OrderState.FAILED}),
    OrderState.SUBMITTED: frozenset(
        {
            OrderState.WORKING,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_REQUESTED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.WORKING: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_REQUESTED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_REQUESTED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.CANCEL_REQUESTED: frozenset(
        {OrderState.CANCELLED, OrderState.FAILED, OrderState.UNKNOWN}
    ),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.FAILED: frozenset(),
    # An UNKNOWN submission outcome is non-terminal for recovery: it may be
    # resolved to the real broker state (e.g. after a lost response).
    OrderState.UNKNOWN: frozenset(
        {
            OrderState.SUBMITTED,
            OrderState.WORKING,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
        }
    ),
}

TERMINAL_STATES = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.FAILED}
)


def can_transition(current: OrderState, target: OrderState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


@dataclass(frozen=True)
class ExecutionIntent:
    """An intent to perform a trade action (broker-agnostic, immutable)."""

    intent_id: str
    trade_id: str
    instrument_figi: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    reason: str = ""
    account_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    idempotency_key: str = ""
    bot_id: int | None = None


@dataclass
class InternalOrder:
    """The internal (live) order linking intent -> broker order id."""

    order_id: str
    intent_id: str
    instrument_figi: str
    side: OrderSide
    order_type: OrderType
    requested_quantity: Decimal
    limit_price: Decimal | None = None
    idempotency_key: str = ""
    account_id: str | None = None
    broker_order_id: str | None = None
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal = Decimal("0")
    status: OrderState = OrderState.CREATED
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    reject_info: str | None = None
    bot_id: int | None = None

    @property
    def remaining_quantity(self) -> Decimal:
        return self.requested_quantity - self.filled_quantity


@dataclass(frozen=True)
class Fill:
    """A single broker execution/fill (immutable)."""

    fill_id: str
    internal_order_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    broker_execution_id: str | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class OrderUpdate:
    """Broker-neutral order-state event (idempotent by broker order id)."""

    broker_order_id: str
    status: OrderState
    internal_order_id: str | None = None
    idempotency_key: str | None = None
    filled_quantity: Decimal | None = None
    average_fill_price: Decimal | None = None
    reject_info: str | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class TradeFill:
    """Broker-neutral trade/execution event (idempotent by execution id)."""

    execution_id: str
    broker_order_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    internal_order_id: str | None = None
    idempotency_key: str | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class PositionUpdate:
    """Broker-neutral position event."""

    instrument_figi: str
    quantity: Decimal
    average_price: Decimal | None = None
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    timestamp: datetime = field(default_factory=_utcnow)
