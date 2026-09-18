"""Execution domain model.

An execution is a fill (full or partial) that produced a change in a position.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Execution(Base):
    """A trade execution (fill) against an order."""

    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id"), index=True, nullable=False
    )
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    commission: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Execution id={self.id} order_id={self.order_id} qty={self.quantity}>"
