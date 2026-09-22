"""Minimal in-memory repositories for the live execution domain.

MVP-6.1 uses in-memory storage so the domain stays runnable without PostgreSQL.
The repository interfaces are kept thin so a real (PostgreSQL) implementation
can be wired later without changing the domain models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.trading.domain import ExecutionIntent, Fill, InternalOrder


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
