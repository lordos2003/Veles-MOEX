"""Durable Deal continuation models (MVP-6.12).

These tables persist the broker-neutral Deal state (one position cycle from the
FLAT entry to the closing take-profit fill). Like the live execution tables they
are self-contained: they store the canonical instrument identifier as a string
and do not join to accounts/instruments, so the trading domain stays
broker-neutral and Deal state reloads without depending on the wider ORM graph.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Deal(Base):
    """Persisted state of one live position cycle (MVP-6.12 D2/D5)."""

    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    instrument_figi: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    deposit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    base_nominal: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("0"), nullable=False
    )
    reference_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("0"), nullable=False
    )
    # D3/D5: per-instrument rounding facts captured at entry so recovery can
    # re-arm the TP with exactly the same lot/tick contract after a restart.
    lot_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    tp_percent: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("0"), nullable=False
    )
    active_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    average_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("0"), nullable=False
    )
    tp_rev: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tp_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    tp_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    tp_intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tp_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tp_broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # MVP-6.16 E1/E2: the simple stop-loss state (one broker stop order per
    # Deal at a time) plus the close reason of the Deal (``take_profit`` /
    # ``stop_loss`` / None while open).
    sl_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    sl_offset: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("0"), nullable=False
    )
    p0_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    sl_rev: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sl_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sl_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    sl_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # MVP-6.16 E3: whether the bot must stop after this Deal's stop close
    # (None = the config forbade None at START; persisted for recovery).
    stop_bot_after: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DealLevel(Base):
    """One planned grid order of a Deal (persisted, broker-neutral)."""

    __tablename__ = "deal_levels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    level_index: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    nominal: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    offset_percent: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("0"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    is_market: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal("0"), nullable=False
    )
    intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
