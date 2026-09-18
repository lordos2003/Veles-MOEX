"""Position Manager.

Per Architecture & Product Specification section 8, the Position Manager stores
quantity, average price, realized/unrealized P&L, fees, opened_at and duration.
Average price is recalculated automatically after DCA.

Trading logic is not implemented yet; this defines the interface.
"""

from __future__ import annotations

from app.brokers import BrokerPosition


class PositionManager:
    """Tracks positions and recalculates average price after DCA."""

    def __init__(self) -> None:
        self._positions: dict[int, BrokerPosition] = {}

    def get(self, instrument_id: int) -> BrokerPosition | None:
        """Return the tracked position for an instrument."""
        return self._positions.get(instrument_id)

    def apply_fill(
        self, instrument_id: int, quantity: float, price: float
    ) -> BrokerPosition:
        """Apply an execution to a position and recalculate average price.

        Average-price recalculation after DCA is implemented later.
        """
        raise NotImplementedError("Position accounting is not implemented yet")

    def mark_to_market(self, instrument_id: int, price: float) -> float:
        """Mark the position to market and return unrealized P&L.

        Unrealized P&L computation is implemented later.
        """
        raise NotImplementedError("Mark-to-market is not implemented yet")

    def close(self, instrument_id: int) -> BrokerPosition | None:
        """Close the tracked position."""
        raise NotImplementedError("Position close is not implemented yet")
