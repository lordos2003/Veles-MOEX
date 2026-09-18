"""Order Manager.

Per Architecture & Product Specification section 7, the Order Manager owns the
order lifecycle (NEW, SUBMITTED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED,
EXPIRED, ERROR) and responsibilities: create, modify, cancel, execution tracking,
partial fills, recovery and synchronization with the broker.

Trading logic is not implemented yet; this defines the interface.
"""

from __future__ import annotations

from app.brokers import BrokerAdapter, BrokerOrder, BrokerOrderRequest


class OrderManager:
    """Manages the order lifecycle against a broker adapter."""

    def __init__(self, broker: BrokerAdapter) -> None:
        self._broker = broker

    async def create(self, request: BrokerOrderRequest) -> BrokerOrder:
        """Create and track an order."""
        raise NotImplementedError("Order creation is not implemented yet")

    async def modify(self, order_id: str, **changes: object) -> None:
        """Modify an order."""
        raise NotImplementedError("Order modification is not implemented yet")

    async def cancel(self, order_id: str) -> None:
        """Cancel an order."""
        raise NotImplementedError("Order cancellation is not implemented yet")

    async def sync(self, order_id: str) -> BrokerOrder:
        """Synchronize order state with the broker."""
        raise NotImplementedError("Order synchronization is not implemented yet")

    async def recover(self) -> list[BrokerOrder]:
        """Recover open orders after reconnect."""
        raise NotImplementedError("Order recovery is not implemented yet")
