"""Bot API schemas (broker-neutral)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


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


class BotDepositUpdate(BaseModel):
    """Write-side contract for the bot deposit (MVP-6.11 C5/C6).

    The ``deposit`` key is required: a ``PATCH`` without it must not silently
    clear the deposit (review observation 2). A positive ``Decimal`` sets the
    deposit; an explicit ``null`` clears it. A non-positive value is rejected
    (FastAPI 422); no default deposit is invented.
    """

    deposit: Decimal | None = Field(gt=0)
