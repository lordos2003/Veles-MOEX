"""Exit Engine.

The Exit Engine is designed around explicit TP types (see the Veles TP
requirements and Architecture & Product Specification section 6):

- FixedPercentageTP
- MultiTakeTP
- SignalTP
- BreakEvenProtection
- StopLoss
- TrailingExit (future/conditional)

Trading mechanics are NOT implemented yet. This module only defines the
interface those subsystems will implement.
"""

from __future__ import annotations

from app.strategies.config import ExitConfig
from app.strategies.domain import ExitPlan


class ExitEngine:
    """Builds exit orders for a position from an ExitConfig."""

    def build_exit_orders(
        self, config: ExitConfig, average_price: float, position_qty: float
    ) -> list[ExitPlan]:
        """Build the initial set of exit orders.

        This covers FixedPercentageTP, MultiTakeTP, SignalTP and trailing logic
        once implemented (MVP-5).
        """
        raise NotImplementedError("Exit mechanics are not implemented yet")

    def on_average(
        self,
        config: ExitConfig,
        average_price: float,
        position_qty: float,
        old_exits: list[ExitPlan],
    ) -> list[ExitPlan]:
        """Rebuild exits after an averaging event.

        Implements cancel-and-replace semantics: old TP cancelled, average price
        recalculated, new TP created. Implemented at MVP-5.
        """
        raise NotImplementedError("Exit recalculation is not implemented yet")
