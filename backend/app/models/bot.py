"""Bot domain model.

A Bot runs one StrategyVersion on an Account/Instrument. It is the live trading
instance. Status transitions are owned by the Trading Engine / Bot lifecycle.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Bot(TimestampMixin, Base):
    """A running/runnable trading bot bound to a strategy version."""

    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("strategy_versions.id"), index=True, nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), index=True, nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id"), index=True, nullable=False
    )
    # e.g. "stopped", "running", "error". Exact vocabulary TBD at MVP-6.
    status: Mapped[str] = mapped_column(String(32), default="stopped", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Bot id={self.id} name={self.name!r} status={self.status!r}>"
