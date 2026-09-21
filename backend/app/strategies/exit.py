"""Exit Engine (basic).

At MVP-2 only the simplest exit is implemented: ``FixedPercentageTP`` builds a
single take-profit exit relative to the entry price. Multi-take, signal TP,
break-even, stop-loss and trailing are later stages (MVP-5).
"""

from __future__ import annotations

from decimal import Decimal

from app.models.enums import OrderSide
from app.strategies.config import Direction, ExitConfig, FixedPercentageTP
from app.strategies.domain import ExitPlan


class ExitEngine:
    """Builds exit orders for a position from an ExitConfig."""

    def build_exit_orders(
        self, config: ExitConfig, direction: Direction, entry_price: Decimal, position_qty: float
    ) -> list[ExitPlan]:
        tp = config.take_profit
        if isinstance(tp, FixedPercentageTP):
            percent = Decimal(str(tp.percent))
            factor = Decimal("1") + percent / Decimal("100")
            if direction == Direction.SHORT:
                factor = Decimal("1") - percent / Decimal("100")
            target = entry_price * factor
            side = OrderSide.SELL if direction == Direction.LONG else OrderSide.BUY
            return [
                ExitPlan(
                    side=side, quantity=position_qty, price=target, offset_percent=tp.percent
                )
            ]
        raise NotImplementedError("Only FixedPercentageTP exit is implemented at MVP-2")

    def on_average(
        self,
        config: ExitConfig,
        average_price: float,
        position_qty: float,
        old_exits: list[ExitPlan],
    ) -> list[ExitPlan]:
        raise NotImplementedError("Exit recalculation is not implemented yet")
