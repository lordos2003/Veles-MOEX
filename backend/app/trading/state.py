"""Durable live-execution state snapshot and store boundary (MVP-6.3).

The trading domain stays broker-neutral and synchronous; durability is handled
through an explicit snapshot exchanged over a |LiveStateStore| boundary. The
OrderManager / PositionManager expose ``snapshot()`` / ``load_state(...)`` and
never depend on SQLAlchemy or a concrete store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from app.trading.domain import ExecutionIntent, Fill, InternalOrder
    from app.trading.position_manager import Position


@dataclass
class LiveStateSnapshot:
    """A point-in-time copy of the live execution state."""

    intents: list[ExecutionIntent] = field(default_factory=list)
    orders: list[InternalOrder] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.intents or self.orders or self.fills or self.positions)


class LiveStateStore(Protocol):
    """Persists and reloads the live execution state snapshot."""

    async def save_snapshot(self, snapshot: LiveStateSnapshot) -> None: ...

    async def load_snapshot(self) -> LiveStateSnapshot: ...


class InMemoryLiveStateStore:
    """In-memory store used by deterministic tests."""

    def __init__(self) -> None:
        self._snapshot = LiveStateSnapshot()

    async def save_snapshot(self, snapshot: LiveStateSnapshot) -> None:
        self._snapshot = snapshot

    async def load_snapshot(self) -> LiveStateSnapshot:
        return self._snapshot
