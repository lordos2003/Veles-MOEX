"""Plan -> ExecutionIntent conversion (broker-neutral, MVP-6.7).

The conversion lives at the Trading Engine / runtime orchestration boundary:
the Strategy Engine itself never touches the Order Manager.

Only plan items that carry safe, real domain values are converted into live
intents:

- DCA/Grid orders (``GridOrder``): side, quantity and optional limit price are
  real values computed by the DCA/Grid Engine.
- Entry signals (``EntrySignal``): the domain carries no order quantity, so an
  entry signal is NOT converted (explicit boundary; no fabricated quantity).
- Exit plans (``ExitPlan``): the quantity currently originates from the
  ``position_qty=1.0`` placeholder in ``StrategyEngine.evaluate()``, so exits
  are NOT converted (explicit boundary; no fabricated quantity). A live exit
  quantity must come from real position state.

Intent ids are deterministic content hashes so repeated evaluation of the same
plan maps to the same intent, preserving the existing ``ExecutionIntent``
idempotency semantics.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from app.models.enums import OrderType
from app.strategies.domain import Plan
from app.trading.domain import ExecutionIntent


def _stable_intent_id(
    bot_id: int, index: int, side: str, quantity: str, price: str | None
) -> str:
    raw = f"bot-{bot_id}:{index}:{side}:{quantity}:{price or 'market'}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"plan-{digest}"


def plan_to_intents(
    plan: Plan,
    *,
    instrument_figi: str,
    bot_id: int,
    account_id: str | None = None,
) -> list[ExecutionIntent]:
    """Convert a strategy Plan into broker-neutral execution intents.

    Only DCA/Grid orders are converted (they carry a real quantity). Entry
    signals and exit plans are intentionally not converted — see the module
    docstring for the explicit boundaries.
    """
    intents: list[ExecutionIntent] = []
    for index, grid in enumerate(plan.grid):
        if grid.quantity <= 0:
            continue
        price = Decimal(str(grid.price)) if grid.price is not None else None
        intents.append(
            ExecutionIntent(
                intent_id=_stable_intent_id(
                    bot_id,
                    index,
                    grid.side.value,
                    str(grid.quantity),
                    str(grid.price) if grid.price is not None else None,
                ),
                trade_id="",
                instrument_figi=instrument_figi,
                side=grid.side,
                order_type=OrderType.LIMIT if price is not None else OrderType.MARKET,
                quantity=Decimal(str(grid.quantity)),
                limit_price=price,
                account_id=account_id,
                bot_id=bot_id,
            )
        )
    return intents
