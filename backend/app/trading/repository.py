"""Repository boundaries for the live execution domain.

The trading domain (OrderManager / PositionManager) depends only on these small
Protocols, never on a concrete storage engine. Two implementations exist:

- In-memory repositories (default, used by deterministic domain tests).
- A SQLAlchemy/PostgreSQL implementation in ``app.persistence.execution_state``
  (wired at composition root for durable live execution state).

This keeps the trading domain broker-neutral and storage-agnostic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from app.trading.domain import ExecutionIntent, Fill, InternalOrder
    from app.trading.position_manager import Position


class IntentRepository(Protocol):
    """Stores execution intents."""

    def save(self, intent: ExecutionIntent) -> None: ...

    def get(self, intent_id: str) -> ExecutionIntent | None: ...

    def list(self) -> list[ExecutionIntent]: ...


class OrderRepository(Protocol):
    """Stores internal orders with intent / idempotency / broker indexes."""

    def save(self, order: InternalOrder) -> None: ...

    def get(self, order_id: str) -> InternalOrder | None: ...

    def get_by_intent(self, intent_id: str) -> InternalOrder | None: ...

    def get_by_idempotency(self, key: str) -> InternalOrder | None: ...

    def get_by_broker(self, broker_order_id: str) -> InternalOrder | None: ...

    def list(self) -> list[InternalOrder]: ...


class FillRepository(Protocol):
    """Stores fills, de-duplicated by fill id."""

    def save(self, fill: Fill) -> None: ...

    def has(self, fill_id: str) -> bool: ...

    def get(self, fill_id: str) -> Fill | None: ...

    def list(self) -> list[Fill]: ...


class PositionRepository(Protocol):
    """Stores broker-neutral position state."""

    def save(self, position: Position) -> None: ...

    def get(self, instrument_figi: str) -> Position | None: ...

    def list(self) -> list[Position]: ...


class InMemoryIntentRepository:
    """Stores execution intents by intent id."""

    def __init__(self) -> None:
        self._items: dict[str, ExecutionIntent] = {}

    def save(self, intent: ExecutionIntent) -> None:
        self._items[intent.intent_id] = intent

    def get(self, intent_id: str) -> ExecutionIntent | None:
        return self._items.get(intent_id)

    def list(self) -> list[ExecutionIntent]:
        return list(self._items.values())

    def clear(self) -> None:
        self._items.clear()


class InMemoryOrderRepository:
    """Stores internal orders with intent / idempotency / broker indexes."""

    def __init__(self) -> None:
        self._by_id: dict[str, InternalOrder] = {}
        self._by_intent: dict[str, str] = {}
        self._by_idempotency: dict[str, str] = {}
        self._by_broker: dict[str, str] = {}

    def save(self, order: InternalOrder) -> None:
        self._by_id[order.order_id] = order
        self._by_intent[order.intent_id] = order.order_id
        if order.idempotency_key:
            self._by_idempotency[order.idempotency_key] = order.order_id
        if order.broker_order_id:
            self._by_broker[order.broker_order_id] = order.order_id

    def get(self, order_id: str) -> InternalOrder | None:
        return self._by_id.get(order_id)

    def get_by_intent(self, intent_id: str) -> InternalOrder | None:
        oid = self._by_intent.get(intent_id)
        return self._by_id.get(oid) if oid else None

    def get_by_idempotency(self, key: str) -> InternalOrder | None:
        oid = self._by_idempotency.get(key)
        return self._by_id.get(oid) if oid else None

    def get_by_broker(self, broker_order_id: str) -> InternalOrder | None:
        oid = self._by_broker.get(broker_order_id)
        return self._by_id.get(oid) if oid else None

    def list(self) -> list[InternalOrder]:
        return list(self._by_id.values())

    def clear(self) -> None:
        self._by_id.clear()
        self._by_intent.clear()
        self._by_idempotency.clear()
        self._by_broker.clear()


class InMemoryFillRepository:
    """Stores fills, de-duplicated by fill id."""

    def __init__(self) -> None:
        self._items: dict[str, Fill] = {}

    def save(self, fill: Fill) -> None:
        self._items[fill.fill_id] = fill

    def has(self, fill_id: str) -> bool:
        return fill_id in self._items

    def get(self, fill_id: str) -> Fill | None:
        return self._items.get(fill_id)

    def list(self) -> list[Fill]:
        return list(self._items.values())

    def clear(self) -> None:
        self._items.clear()


class InMemoryPositionRepository:
    """Stores broker-neutral position state by instrument."""

    def __init__(self) -> None:
        self._items: dict[str, Position] = {}

    def save(self, position: Position) -> None:
        self._items[position.instrument_figi] = position

    def get(self, instrument_figi: str) -> Position | None:
        return self._items.get(instrument_figi)

    def list(self) -> list[Position]:
        return list(self._items.values())
