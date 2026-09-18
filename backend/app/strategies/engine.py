"""Strategy Engine.

The Strategy Engine is configuration-driven (Architecture & Product
Specification section 3). It orchestrates the Entry, DCA/Grid and Exit engines
and produces a Plan for the Trading Engine. It must not know about a broker.
"""

from __future__ import annotations

from app.strategies.config import StrategyConfig
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import MarketContext, Plan
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine


class StrategyEngine:
    """Coordinates Entry / DCA-Grid / Exit engines around a StrategyConfig."""

    def __init__(
        self,
        entry: EntryEngine,
        dca_grid: DCAGridEngine,
        exit_engine: ExitEngine,
    ) -> None:
        self.entry = entry
        self.dca_grid = dca_grid
        self.exit_engine = exit_engine

    def evaluate(self, config: StrategyConfig, context: MarketContext) -> Plan:
        """Evaluate the strategy against a market snapshot and return a Plan.

        Full orchestration is implemented later; the method currently exposes
        the intended contract.
        """
        raise NotImplementedError("Strategy evaluation is not implemented yet")
