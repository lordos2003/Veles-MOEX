"""Entry Engine.

Per Architecture & Product Specification section 4, the Entry Engine evaluates
opening conditions (Veles-style filters/signals) and produces a trading signal.
It does NOT send broker orders.
"""

from __future__ import annotations

from app.models.enums import OrderSide
from app.strategies.config import Direction, EntryConfig
from app.strategies.domain import EntrySignal, MarketContext
from app.strategies.filters import FilterEvaluator


class EntryEngine:
    """Evaluates entry filters and emits an entry signal."""

    def __init__(self, evaluator: FilterEvaluator | None = None) -> None:
        self._evaluator = evaluator or FilterEvaluator()

    def evaluate(
        self, entry: EntryConfig, direction: Direction, context: MarketContext
    ) -> EntrySignal | None:
        """Return an EntrySignal when entry conditions are met, else None."""
        if context.snapshot is None or context.timestamp is None:
            return None
        fired = self._evaluator.evaluate(
            entry.groups, entry.method, context.snapshot, context.timestamp
        )
        if not fired:
            return None
        return EntrySignal(
            action="enter",
            direction=OrderSide.BUY if direction == Direction.LONG else OrderSide.SELL,
        )
