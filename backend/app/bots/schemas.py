"""Bot API schemas (broker-neutral)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BotResponse(BaseModel):
    id: int
    name: str
    status: str
    strategy_version_id: int | None = None
    account_id: int | None = None
    instrument_id: int | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
