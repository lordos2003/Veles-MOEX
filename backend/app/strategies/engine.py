"""Strategy Engine.

The Strategy Engine is configuration-driven (Architecture & Product
Specification section 3) and must not know about a broker. It orchestrates the
Entry engine (Veles-style filters) and a basic Exit, producing a Plan for the
Trading Engine.
"""

from __future__ import annotations

from decimal import Decimal

from app.strategies.config import StrategyConfig
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import MarketContext, Plan
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine


class StrategyEngine:
    """Coordinates Entry / Exit engines around a StrategyConfig."""

    def __init__(
        self, entry: EntryEngine, dca_grid: DCAGridEngine, exit_engine: ExitEngine
    ) -> None:
        self.entry = entry
        self.dca_grid = dca_grid
        self.exit_engine = exit_engine

    def evaluate(self, config: StrategyConfig, context: MarketContext) -> Plan:
        signal = self.entry.evaluate(config.entry, config.direction, context)
        exits = []
        if signal is not None:
            entry_price = self._entry_price(config, context)
            exits = self.exit_engine.build_exit_orders(
                config.exit, config.direction, entry_price, position_qty=1.0
            )
        return Plan(entry=signal, exits=exits)

    @staticmethod
    def _entry_price(config: StrategyConfig, context: MarketContext) -> Decimal:
        if context.price is not None:
            return Decimal(str(context.price))
        if context.snapshot is not None:
            # Fall back to the latest close of the first available series.
            for series in context.snapshot.series.values():
                if series.bars:
                    return Decimal(str(series.bars[-1].close))
        return Decimal("0")
