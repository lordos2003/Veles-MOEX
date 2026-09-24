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
from app.strategies.domain import GridOrder, MarketContext, Plan
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

    def evaluate(
        self,
        config: StrategyConfig,
        context: MarketContext,
        *,
        base_nominal: Decimal | None = None,
        position_qty: Decimal | None = None,
    ) -> Plan:
        signal = self.entry.evaluate(config.entry, config.direction, context)
        exits = []
        grid = []
        if signal is not None:
            entry_price = self._entry_price(config, context)
            # Exit plans are built only with a real, positive position quantity
            # (sourced by the PositionManager in the live path). No placeholder
            # (position_qty=1.0) is used; without a real quantity no exits are
            # planned. The DCA/Grid plan is built only when an explicit live
            # sizing source (base nominal) is supplied; the engine's
            # Decimal("100") default is never relied upon by live execution.
            if position_qty is not None and position_qty > 0:
                exits = self.exit_engine.build_exit_orders(
                    config.exit,
                    config.direction,
                    entry_price,
                    position_qty=float(position_qty),
                )
            if base_nominal is not None and base_nominal > 0 and entry_price > 0:
                grid_state = self.dca_grid.build(
                    config.dca_grid,
                    entry_price,
                    config.direction,
                    base_nominal=base_nominal,
                )
                grid = [
                    GridOrder(
                        side=plan.side,
                        quantity=float(plan.quantity),
                        price=None if plan.is_market else float(plan.price),
                        offset_percent=plan.offset_percent,
                    )
                    for plan in grid_state.active_orders()
                ]
        return Plan(entry=signal, grid=grid, exits=exits)

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
