"""DCA / Grid Engine.

Per Architecture & Product Specification section 5, this builds the initial
order plus averaging/grid levels and recalculates the grid after averaging.
"""

from __future__ import annotations

from app.strategies.config import DCAGridConfig
from app.strategies.domain import GridOrder


class DCAGridEngine:
    """Builds and recalculates DCA/grid order levels."""

    def build_grid(self, config: DCAGridConfig, reference_price: float) -> list[GridOrder]:
        """Build the grid from the configuration for a reference price.

        Grid mechanics (spacing, martingale, logarithmic distribution, pull-up)
        are implemented at MVP-4.
        """
        raise NotImplementedError("DCA/Grid mechanics are not implemented yet")

    def recalculate(
        self, config: DCAGridConfig, position_qty: float, reference_price: float
    ) -> list[GridOrder]:
        """Recalculate the grid after an averaging event.

        Grid recalculation after averaging is implemented at MVP-4.
        """
        raise NotImplementedError("DCA/Grid recalculation is not implemented yet")
