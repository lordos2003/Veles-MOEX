"""Bot API schemas (broker-neutral)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class BotResponse(BaseModel):
    id: int
    name: str
    status: str
    strategy_version_id: int | None = None
    account_id: int | None = None
    instrument_id: int | None = None
    # The bot deposit (MVP-6.11 C5); None when unset.
    deposit: Decimal | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    # MVP-6.16 E3: why the bot was stopped (``"stop-loss"`` after a protective
    # stop close with ``stop_bot_after=true``; None for manual stops).
    stop_reason: str | None = None
    # B2 (MVP-6.12 correction round 1): the last Deal-layer failure reason for
    # this bot (None when no deal failure has been recorded). Read-only.
    deal_error: str | None = None
    # MVP-6.13 S4: the last live-cycle failure reason recorded by the cycle
    # scheduler (None when the scheduler has not recorded one). Read-only and
    # generic (transient-skip reason or the terminal error that moved the bot
    # to ERROR); distinct from the deal-specific `deal_error` above.
    last_error: str | None = None
    # MVP-6.14 N1: the last proven no-trade skip reason (the tick was skipped —
    # not a failure and not a success). Read-only, in-memory scheduler state.
    last_skip_reason: str | None = None


class BotCreate(BaseModel):
    """Create a bot bound to an existing immutable strategy version (R5).

    ``deposit`` is optional and validated the same way as PATCH (>0, no default
    invented). The bot is created in state STOPPED; it starts only via
    ``POST /bots/{id}/start``.
    """

    name: str = Field(min_length=1, max_length=128)
    strategy_version_id: int
    account_id: int
    instrument_id: int
    deposit: Decimal | None = Field(default=None, gt=0)


class BotUpdate(BaseModel):
    """Update a bot: deposit and/or strategy version (R5).

    All keys are optional. ``strategy_version_id`` may only change while the
    bot is STOPPED and has no unclosed deal — otherwise HTTP 409. ``deposit``
    may be set/cleared any time (same rules as MVP-6.11 C5). An empty PATCH is
    rejected (422): a PATCH without keys is a client error, not a silent no-op.
    """

    deposit: Decimal | None = Field(default=None, gt=0)
    strategy_version_id: int | None = None

    @model_validator(mode="after")
    def _require_some_key(self) -> BotUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one of deposit / strategy_version_id is required")
        return self


class BotDepositUpdate(BaseModel):
    """Write-side contract for the bot deposit (MVP-6.11 C5/C6).

    The ``deposit`` key is required: a ``PATCH`` without it must not silently
    clear the deposit (review observation 2). A positive ``Decimal`` sets the
    deposit; an explicit ``null`` clears it. A non-positive value is rejected
    (FastAPI 422); no default deposit is invented.
    """

    deposit: Decimal | None = Field(gt=0)


class DealLevelResponse(BaseModel):
    """One planned grid order of a deal (R6)."""

    index: int
    side: str
    price: Decimal | None = None
    nominal: Decimal
    quantity: Decimal
    offset_percent: float
    status: str
    is_market: bool = False
    filled_quantity: Decimal = Decimal("0")
    order_id: str | None = None
    broker_order_id: str | None = None


class DealResponse(BaseModel):
    """The persisted state of one position cycle (R6, read-only projection)."""

    id: int
    bot_id: int | None = None
    instrument_figi: str
    direction: str
    status: str
    deposit: Decimal | None = None
    base_nominal: Decimal = Decimal("0")
    reference_price: Decimal = Decimal("0")
    lot_size: int | None = None
    tick_size: Decimal | None = None
    tp_percent: float = 0.0
    average_price: Decimal = Decimal("0")
    # R6: current position volume = sum of filled level quantities (projection).
    position_quantity: Decimal = Decimal("0")
    tp_price: Decimal | None = None
    tp_quantity: Decimal | None = None
    sl_percent: float | None = None
    p0_price: Decimal | None = None
    sl_quantity: Decimal | None = None
    sl_price: Decimal | None = None
    sl_order_id: str | None = None
    # R6: stop state — None when not configured, True while a stop order is
    # placed (sl_order_id present), False when configured but disarmed.
    sl_active: bool | None = None
    close_reason: str | None = None
    stop_bot_after: bool | None = None
    levels: list[DealLevelResponse] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
