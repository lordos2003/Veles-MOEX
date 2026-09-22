"""Durable live execution state models (MVP-6.3).

These tables persist the broker-neutral live execution domain so an active bot
can be recovered after a process restart or stream reconnect. They are
self-contained (they store the canonical instrument identifier as a string and
do not join to accounts/instruments via foreign keys) so that the trading domain
stays broker-neutral and the live state can be reloaded without depending on the
wider product ORM graph.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class LiveIntent(Base):
    """Persisted execution intent (broker-neutral)."""

    __tablename__ = "live_intents"

    intent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_figi: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class LiveOrder(Base):
    """Persisted internal order linking intent -> broker order id."""

    __tablename__ = "live_orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    instrument_figi: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    filled_quantity: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    average_fill_price: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reject_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class LiveFill(Base):
    """Persisted fill/execution record."""

    __tablename__ = "live_fills"

    fill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    internal_order_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    fee: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    broker_execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class LivePosition(Base):
    """Persisted broker-neutral position state."""

    __tablename__ = "live_positions"

    instrument_figi: Mapped[str] = mapped_column(String(64), primary_key=True)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    average_price: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    fees: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    current_price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
