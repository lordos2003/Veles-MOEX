"""Risk Manager.

Per Architecture & Product Specification section 9, the Risk Manager is separate
from the strategy and controls maximum position size, available capital, risk
limits, number of simultaneous bots, instrument limits, daily limits and
emergency stop. The strategy cannot bypass the Risk Manager.

Risk rules are not implemented yet; this defines the interface.
"""

from __future__ import annotations


class RiskManager:
    """Authoritative guard on trade/position risk."""

    def check_order(self, request: object) -> bool:
        """Reject or allow an order request.

        Raise/return False when the order violates a risk limit. Implemented as
        part of MVP-6.
        """
        raise NotImplementedError("Risk checks are not implemented yet")

    def check_start(self, bot_id: int) -> bool:
        """Allow/deny starting a bot (max concurrent bots, daily limits)."""
        raise NotImplementedError("Risk start checks are not implemented yet")

    def check_emergency_stop(self) -> bool:
        """Return whether emergency stop is triggered."""
        raise NotImplementedError("Emergency stop is not implemented yet")
