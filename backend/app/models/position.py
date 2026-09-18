"""Position domain model.

Fields follow Architecture & Product Specification section 8. Average price is
recalculated automatically after DCA by the Position Manager (not here).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Position(TimestampMixin, Base):
    """An open (or recently closed) position."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), index=True, nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id"), index=True, nullable=False
    )
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    average_price: Mapped[float | None] = mapped_column(
        Numeric(20, 8), nullable=True
    )
    realized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    fees: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Position duration (seconds), see spec section 8.
    duration: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Position id={self.id} qty={self.quantity} avg={self.average_price}>"
