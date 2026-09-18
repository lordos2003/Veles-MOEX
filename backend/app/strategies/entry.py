"""Entry Engine.

Per Architecture & Product Specification section 4, the Entry Engine evaluates
opening conditions and produces trading signals. It does NOT send broker orders.
"""

from __future__ import annotations

from app.strategies.config import EntryConfig
from app.strategies.domain import EntrySignal, MarketContext


class EntryEngine:
    """Evaluates entry conditions and emits an entry signal."""

    def evaluate(self, config: EntryConfig, context: MarketContext) -> EntrySignal | None:
        """Return an EntrySignal when entry conditions are met, else None.

        Not implemented yet; wiring is scheduled for MVP-2.
        """
        raise NotImplementedError("Entry evaluation is not implemented yet")
