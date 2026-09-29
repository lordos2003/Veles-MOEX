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


class BotDepositUpdate(BaseModel):
    """Write-side contract for the bot deposit (MVP-6.11 C5).

    A positive ``Decimal`` sets the deposit; ``None`` clears it. A non-positive
    value is rejected (FastAPI 422); no default deposit is invented.
    """

    deposit: Decimal | None = Field(default=None, gt=0)
