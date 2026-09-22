"""Order Manager (broker-neutral, MVP-6.1).

The Order Manager translates an |ExecutionIntent| into a broker call, tracks the
internal order lifecycle, enforces idempotency, applies fills/updates, and
forwards actual fills to the |PositionManager|.

It does NOT make strategy, DCA, TP or SL decisions. Those belong to the
Strategy/Trading/Exit layers.

T-Invest is never imported here; the broker is the broker-neutral BrokerAdapter.
"""

from __future__ import annotations

import uuid

from app.brokers.base import BrokerAdapter, BrokerOrder, BrokerOrderRequest
from app.models.enums import OrderStatus
from app.trading.domain import (
    ALLOWED_TRANSITIONS,
    ExecutionIntent,
    Fill,
    InternalOrder,
    OrderState,
    OrderUpdate,
    PositionUpdate,
    TradeFill,
    _utcnow,
)
from app.trading.position_manager import PositionManager
from app.trading.repository import (
    InMemoryFillRepository,
    InMemoryIntentRepository,
    InMemoryOrderRepository,
)
from app.trading.state import LiveStateSnapshot

_BROKER_STATUS_MAP = {
    OrderStatus.NEW: OrderState.SUBMITTED,
    OrderStatus.SUBMITTED: OrderState.SUBMITTED,
    OrderStatus.PARTIALLY_FILLED: OrderState.PARTIALLY_FILLED,
    OrderStatus.FILLED: OrderState.FILLED,
    OrderStatus.CANCELLED: OrderState.CANCELLED,
    OrderStatus.REJECTED: OrderState.REJECTED,
    OrderStatus.EXPIRED: OrderState.CANCELLED,
    OrderStatus.ERROR: OrderState.FAILED,
}


def _ensure_idempotency(intent: ExecutionIntent) -> str:
    """Return a stable idempotency key for a given execution intent.

    A key supplied on the intent is preserved (it must be reused verbatim on
    retry); an absent key is generated once as a UUID4. The key must never be
    regenerated for the same intent — that would break idempotent retry.
    """
    key = (intent.idempotency_key or "").strip()
    if key:
        return key
    return str(uuid.uuid4())


class OrderStateError(RuntimeError):
    """Raised when an invalid order-state transition is requested."""


class OrderManager:
    """Owns the live order lifecycle and forwards fills to positions."""

    def __init__(
        self,
        broker: BrokerAdapter,
        position_manager: PositionManager | None = None,
        *,
        intent_repo: InMemoryIntentRepository | None = None,
        order_repo: InMemoryOrderRepository | None = None,
        fill_repo: InMemoryFillRepository | None = None,
    ) -> None:
        self._broker = broker
        self._positions = position_manager or PositionManager()
        self._intents = intent_repo or InMemoryIntentRepository()
        self._orders = order_repo or InMemoryOrderRepository()
        self._fills = fill_repo or InMemoryFillRepository()
        self._order_seq = 0

    # --- intents ------------------------------------------------------------------

    def create_intent(self, **fields) -> ExecutionIntent:
        intent = ExecutionIntent(**fields)
        self._intents.save(intent)
        return intent

    def get_intent(self, intent_id: str) -> ExecutionIntent | None:
        return self._intents.get(intent_id)

    def list_intents(self) -> list[ExecutionIntent]:
        return self._intents.list()

    def snapshot(self) -> LiveStateSnapshot:
        """Snapshot the live execution state for durable persistence."""
        return LiveStateSnapshot(
            intents=self._intents.list(),
            orders=self._orders.list(),
            fills=self._fills.list(),
            positions=self._positions.list(),
        )

    def load_snapshot(self, snapshot: LiveStateSnapshot) -> None:
        """Restore the live execution state from a recovered snapshot."""
        self._intents.clear()
        self._orders.clear()
        self._fills.clear()
        for intent in snapshot.intents:
            self._intents.save(intent)
        for order in snapshot.orders:
            self._orders.save(order)
        for fill in snapshot.fills:
            self._fills.save(fill)
        self._positions.load_state(snapshot.positions)
        self._order_seq = self._max_order_seq()

    def _max_order_seq(self) -> int:
        max_seq = 0
        for order in self._orders.list():
            try:
                seq = int(order.order_id.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                continue
            max_seq = max(max_seq, seq)
        return max_seq

    # --- submission ---------------------------------------------------------------

    async def submit(self, intent: ExecutionIntent) -> InternalOrder:
        existing = self._find_duplicate(intent)
        if existing is not None:
            return existing
        if intent.quantity <= 0:
            return self._reject(intent, "quantity must be positive")

        order = self._new_order(intent)
        self._orders.save(order)
        # Mark the submission attempt as SUBMITTED; a lost response may then
        # legitimately transition to UNKNOWN (await reconciliation).
        self._transition(order, OrderState.SUBMITTED)

        request = self._build_request(order)
        try:
            broker_order = await self._broker.place_order(request)
        except Exception:
            self._transition(order, OrderState.UNKNOWN)
            return order

        if broker_order is None:
            self._transition(order, OrderState.UNKNOWN)
            return order

        order.broker_order_id = broker_order.order_id
        self._orders.save(order)
        self._apply_broker_status(order, broker_order)
        return order

    def _find_duplicate(self, intent: ExecutionIntent) -> InternalOrder | None:
        order = self._orders.get_by_intent(intent.intent_id)
        if order is not None:
            return order
        if intent.idempotency_key:
            return self._orders.get_by_idempotency(intent.idempotency_key)
        return None

    def _new_order(self, intent: ExecutionIntent) -> InternalOrder:
        self._order_seq += 1
        return InternalOrder(
            order_id=f"order-{self._order_seq}",
            intent_id=intent.intent_id,
            instrument_figi=intent.instrument_figi,
            side=intent.side,
            order_type=intent.order_type,
            requested_quantity=intent.quantity,
            limit_price=intent.limit_price,
            idempotency_key=_ensure_idempotency(intent),
            account_id=intent.account_id,
            created_at=_utcnow(),
        )

    def _reject(self, intent: ExecutionIntent, reason: str) -> InternalOrder:
        self._order_seq += 1
        order = InternalOrder(
            order_id=f"order-{self._order_seq}",
            intent_id=intent.intent_id,
            instrument_figi=intent.instrument_figi,
            side=intent.side,
            order_type=intent.order_type,
            requested_quantity=intent.quantity,
            limit_price=intent.limit_price,
            idempotency_key=_ensure_idempotency(intent),
            account_id=intent.account_id,
            status=OrderState.REJECTED,
            reject_info=reason,
            created_at=_utcnow(),
        )
        self._orders.save(order)
        return order

    @staticmethod
    def _build_request(order: InternalOrder) -> BrokerOrderRequest:
        return BrokerOrderRequest(
            instrument_figi=order.instrument_figi,
            side=order.side,
            quantity=order.requested_quantity,
            type=order.order_type,
            price=order.limit_price,
            account_id=order.account_id,
            idempotency_key=order.idempotency_key,
        )

    def _apply_broker_status(self, order: InternalOrder, broker_order: BrokerOrder) -> None:
        if broker_order.status == OrderStatus.REJECTED:
            self._transition(order, OrderState.REJECTED)
            order.reject_info = broker_order.reject_info
            return
        if broker_order.status == OrderStatus.ERROR:
            self._transition(order, OrderState.FAILED)
            order.reject_info = broker_order.reject_info
            return
        target = _BROKER_STATUS_MAP.get(broker_order.status)
        if target is None:
            self._transition(order, OrderState.UNKNOWN)
            return
        self._transition(order, target)

    # --- fill / event handling ----------------------------------------------------

    def apply_fill(self, fill: Fill) -> None:
        """Apply a fill idempotently (duplicate fill ids are ignored)."""
        if self._fills.has(fill.fill_id):
            return
        self._fills.save(fill)
        order = self._orders.get(fill.internal_order_id)
        if order is None:
            return

        prev_filled = order.filled_quantity
        order.filled_quantity += fill.quantity
        if prev_filled == 0 and fill.quantity > 0:
            order.average_fill_price = fill.price
        else:
            order.average_fill_price = (
                order.average_fill_price * prev_filled + fill.price * fill.quantity
            ) / order.filled_quantity
        order.updated_at = fill.timestamp

        if order.filled_quantity >= order.requested_quantity:
            self._transition(order, OrderState.FILLED)
        else:
            self._transition(order, OrderState.PARTIALLY_FILLED)

        if self._positions is not None:
            self._positions.apply_fill(
                order.instrument_figi,
                order.side,
                fill.quantity,
                fill.price,
                fill.fee,
                fill.timestamp,
            )

    def on_order_update(self, update: OrderUpdate) -> None:
        """Apply a broker order-state event idempotently."""
        order = self._resolve_order(
            update.broker_order_id, update.internal_order_id, update.idempotency_key
        )
        if order is None:
            return
        # The stream may deliver the exchange order id only after submission; adopt
        # it so subsequent events/operations can be correlated to this order.
        if update.broker_order_id and not order.broker_order_id:
            order.broker_order_id = update.broker_order_id
            self._orders.save(order)
        if update.status != order.status:
            self._transition(order, update.status)
        if update.filled_quantity is not None:
            order.filled_quantity = update.filled_quantity
        if update.average_fill_price is not None:
            order.average_fill_price = update.average_fill_price
        if update.reject_info:
            order.reject_info = update.reject_info
        order.updated_at = update.timestamp

    def on_trade_fill(self, trade: TradeFill) -> None:
        order = self._resolve_order(
            trade.broker_order_id, trade.internal_order_id, trade.idempotency_key
        )
        if order is None:
            return
        fill = Fill(
            fill_id=trade.execution_id,
            internal_order_id=order.order_id,
            quantity=trade.quantity,
            price=trade.price,
            fee=trade.fee,
            broker_execution_id=trade.execution_id,
            timestamp=trade.timestamp,
        )
        self.apply_fill(fill)

    def _resolve_order(
        self,
        broker_order_id: str | None,
        internal_order_id: str | None,
        idempotency_key: str | None = None,
    ) -> InternalOrder | None:
        order = self._orders.get_by_broker(broker_order_id) if broker_order_id else None
        if order is None and idempotency_key:
            order = self._orders.get_by_idempotency(idempotency_key)
        if order is None and internal_order_id:
            order = self._orders.get(internal_order_id)
        return order

    def on_position_update(self, update: PositionUpdate) -> None:
        if self._positions is not None:
            self._positions.apply_position_update(update)

    # --- cancellation / queries ---------------------------------------------------

    async def cancel(self, order_id: str) -> InternalOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(order_id)
        if order.status in {
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
        }:
            return order
        self._transition(order, OrderState.CANCEL_REQUESTED)
        if order.broker_order_id is not None:
            try:
                await self._broker.cancel_order(order.broker_order_id, order.account_id)
                self._transition(order, OrderState.CANCELLED)
            except Exception:
                self._transition(order, OrderState.UNKNOWN)
        else:
            self._transition(order, OrderState.CANCELLED)
        return order

    async def refresh(self, order_id: str) -> InternalOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(order_id)
        if order.broker_order_id is None:
            return order
        try:
            broker_order = await self._broker.get_order(order.broker_order_id, order.account_id)
        except Exception:
            self._transition(order, OrderState.UNKNOWN)
            return order
        self._apply_broker_status(order, broker_order)
        return order

    def get_order(self, order_id: str) -> InternalOrder | None:
        return self._orders.get(order_id)

    def list_orders(self) -> list[InternalOrder]:
        return self._orders.list()

    def list_fills(self) -> list[Fill]:
        return self._fills.list()

    def record_fill(self, fill: Fill) -> None:
        """Record a fill for deduplication without re-applying it to order/position.

        Used by reconciliation so already-known executions (from broker facts)
        are never applied twice by later stream events. Duplicate fill ids are
        ignored.
        """
        if self._fills.has(fill.fill_id):
            return
        self._fills.save(fill)

    def find_by_broker(self, broker_order_id: str) -> InternalOrder | None:
        return self._orders.get_by_broker(broker_order_id)

    def positions(self) -> PositionManager:
        return self._positions

    # --- lifecycle ----------------------------------------------------------------

    @staticmethod
    def _transition(order: InternalOrder, target: OrderState) -> None:
        if order.status == target:
            return
        if target not in ALLOWED_TRANSITIONS.get(order.status, frozenset()):
            raise OrderStateError(
                f"invalid transition {order.status.value} -> {target.value}"
            )
        order.status = target
        order.updated_at = _utcnow()
