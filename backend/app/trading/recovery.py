"""Live execution reconciliation / recovery (MVP-6.3).

The coordinator makes the live execution state durable and reconciles it against
broker facts after a process restart or a stream reconnect. It prefers broker
facts over stale in-memory assumptions and will block unsafe new execution when
an active order cannot be resolved to a known broker state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.brokers.base import BrokerAdapter
from app.models.enums import OrderStatus
from app.trading.domain import TERMINAL_STATES, OrderState, OrderUpdate, PositionUpdate
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.state import LiveStateStore

_ORDER_STATUS_TO_STATE = {
    OrderStatus.NEW: OrderState.SUBMITTED,
    OrderStatus.SUBMITTED: OrderState.SUBMITTED,
    OrderStatus.PARTIALLY_FILLED: OrderState.PARTIALLY_FILLED,
    OrderStatus.FILLED: OrderState.FILLED,
    OrderStatus.CANCELLED: OrderState.CANCELLED,
    OrderStatus.REJECTED: OrderState.REJECTED,
    OrderStatus.EXPIRED: OrderState.CANCELLED,
    OrderStatus.ERROR: OrderState.FAILED,
    OrderStatus.UNKNOWN: OrderState.UNKNOWN,
}


class RecoveryStatus(StrEnum):
    SAFE = "SAFE"
    BLOCKED = "BLOCKED"


@dataclass
class RecoveryResult:
    status: RecoveryStatus
    reason: str | None = None
    recovered_orders: int = 0
    recovered_positions: int = 0

    @property
    def safe(self) -> bool:
        return self.status == RecoveryStatus.SAFE


class LiveRecoveryCoordinator:
    """Reconciles durable local state with broker facts before execution resumes."""

    def __init__(
        self,
        store: LiveStateStore,
        order_manager: OrderManager,
        position_manager: PositionManager,
        broker: BrokerAdapter,
    ) -> None:
        self._store = store
        self._order_manager = order_manager
        self._position_manager = position_manager
        self._broker = broker

    async def persist_snapshot(self) -> None:
        """Persist the current in-memory live state to the durable store."""
        await self._store.save_snapshot(self._order_manager.snapshot())

    async def recover(self, account_id: str) -> RecoveryResult:
        """Load durable state and reconcile it against broker facts.

        Returns a RecoveryResult. When the status is BLOCKED, orders that could
        not be safely resolved remain UNKNOWN and unsafe new execution must not
        resume.
        """
        snapshot = await self._store.load_snapshot()
        self._order_manager.load_snapshot(snapshot)

        broker_orders = await self._broker.get_orders(account_id)
        by_broker_id = {order.order_id: order for order in broker_orders}
        by_idempotency = {
            order.idempotency_key: order
            for order in broker_orders
            if order.idempotency_key
        }

        recovered_orders = 0
        unresolved: list[str] = []
        for order in list(self._order_manager.list_orders()):
            if order.status in TERMINAL_STATES:
                continue
            broker_order = self._match(order, by_broker_id, by_idempotency)
            if broker_order is None and order.broker_order_id:
                try:
                    broker_order = await self._broker.get_order(order.broker_order_id, account_id)
                except Exception:
                    broker_order = None
            if broker_order is None:
                unresolved.append(order.order_id)
                self._order_manager.on_order_update(
                    OrderUpdate(
                        broker_order_id=order.broker_order_id,
                        status=OrderState.UNKNOWN,
                        idempotency_key=order.idempotency_key,
                    )
                )
                continue
            if order.broker_order_id is None and broker_order.order_id:
                order.broker_order_id = broker_order.order_id
            try:
                self._order_manager.on_order_update(
                    OrderUpdate(
                        broker_order_id=broker_order.order_id,
                        status=_ORDER_STATUS_TO_STATE.get(broker_order.status, OrderState.UNKNOWN),
                        idempotency_key=order.idempotency_key,
                        reject_info=broker_order.reject_info,
                    )
                )
                recovered_orders += 1
            except Exception:
                unresolved.append(order.order_id)

        recovered_positions = 0
        for position in await self._broker.get_open_positions(account_id):
            self._order_manager.on_position_update(
                PositionUpdate(
                    instrument_figi=position.instrument_figi,
                    quantity=position.quantity,
                    average_price=position.average_price,
                    current_price=position.current_price,
                    unrealized_pnl=position.unrealized_pnl,
                    timestamp=position.timestamp or datetime.now(UTC),
                )
            )
            recovered_positions += 1

        blocked = bool(unresolved)
        reason = f"unresolved active orders: {', '.join(unresolved)}" if blocked else None

        await self.persist_snapshot()

        return RecoveryResult(
            status=RecoveryStatus.BLOCKED if blocked else RecoveryStatus.SAFE,
            reason=reason,
            recovered_orders=recovered_orders,
            recovered_positions=recovered_positions,
        )

    def _match(self, order, by_broker_id, by_idempotency):
        if order.broker_order_id and order.broker_order_id in by_broker_id:
            return by_broker_id[order.broker_order_id]
        if order.idempotency_key and order.idempotency_key in by_idempotency:
            return by_idempotency[order.idempotency_key]
        return None
