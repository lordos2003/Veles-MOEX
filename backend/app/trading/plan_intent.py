"""Plan -> ExecutionIntent conversion (broker-neutral, MVP-6.7 / MVP-6.9).

The conversion lives at the Trading Engine / runtime orchestration boundary:
the Strategy Engine itself never touches the Order Manager.

Plan items are converted when they carry safe, real domain values:

- DCA/Grid orders (``GridOrder``): side, quantity and optional limit price are
  real values computed by the DCA/Grid Engine.
- Exit plans (``ExitPlan``): converted only when they carry a real, positive
  position quantity sourced by the PositionManager. The old
  ``position_qty=1.0`` placeholder is gone (MVP-6.9); an ExitPlan whose quantity
  is not positive is never converted into a live order.
- Entry signals (``EntrySignal``): the domain carries no order quantity, so an
  entry signal is NOT converted (explicit boundary; no fabricated quantity).

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
    raw = f"bot-{bot_id}:grid:{index}:{side}:{quantity}:{price or 'market'}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"plan-{digest}"


def _stable_exit_intent_id(
    bot_id: int, index: int, side: str, quantity: str, price: str | None
) -> str:
    raw = f"bot-{bot_id}:exit:{index}:{side}:{quantity}:{price or 'market'}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"exit-{digest}"


def _intent_for_grid(
    index: int, grid, instrument_figi: str, bot_id: int, account_id: str | None
) -> ExecutionIntent | None:
    if grid.quantity <= 0:
        return None
    price = Decimal(str(grid.price)) if grid.price is not None else None
    return ExecutionIntent(
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


def _intent_for_exit(
    index: int, exit_plan, instrument_figi: str, bot_id: int, account_id: str | None
) -> ExecutionIntent | None:
    if exit_plan.quantity <= 0:
        return None
    price = exit_plan.price
    return ExecutionIntent(
        intent_id=_stable_exit_intent_id(
            bot_id,
            index,
            exit_plan.side.value,
            str(exit_plan.quantity),
            str(exit_plan.price) if exit_plan.price is not None else None,
        ),
        trade_id="",
        instrument_figi=instrument_figi,
        side=exit_plan.side,
        order_type=OrderType.LIMIT if price is not None else OrderType.MARKET,
        quantity=Decimal(str(exit_plan.quantity)),
        limit_price=price,
        account_id=account_id,
        bot_id=bot_id,
    )


def plan_to_intents(
    plan: Plan,
    *,
    instrument_figi: str,
    bot_id: int,
    account_id: str | None = None,
) -> list[ExecutionIntent]:
    """Convert a strategy Plan into broker-neutral execution intents.

    DCA/Grid orders and exit plans (with a positive real quantity) are
    converted; non-positive quantities are skipped. Entry signals are
    intentionally not converted — see the module docstring for the explicit
    boundaries.
    """
    intents: list[ExecutionIntent] = []
    for index, grid in enumerate(plan.grid):
        intent = _intent_for_grid(index, grid, instrument_figi, bot_id, account_id)
        if intent is not None:
            intents.append(intent)
    for index, exit_plan in enumerate(plan.exits):
        intent = _intent_for_exit(index, exit_plan, instrument_figi, bot_id, account_id)
        if intent is not None:
            intents.append(intent)
    return intents
