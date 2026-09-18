"""Order domain model.

Stores broker orders and their lifecycle. Order status/state transitions are
managed by the Order Manager; this model is a passive record.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import OrderSide, OrderStatus, OrderType


class Order(TimestampMixin, Base):
    """A broker order."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Broker-assigned order id, when known.
    external_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), index=True, nullable=False
    )
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id"), index=True, nullable=False
    )
    side: Mapped[OrderSide] = mapped_column(String(8), nullable=False)
    type: Mapped[OrderType] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    filled_quantity: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(String(32), default=OrderStatus.NEW, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Order id={self.id} status={self.status!s} side={self.side!s}>"
