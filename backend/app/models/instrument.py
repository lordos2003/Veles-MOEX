"""Instrument domain model.

Represents a tradable MOEX instrument surfaced through T-Invest. MOEX-specific
properties (lot size, tick size, trading sessions, clearing periods, trading
modes) are the reason this entity exists as a first-class model and will be
extended as the market data layer is built out.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Instrument(TimestampMixin, Base):
    """Tradable instrument metadata."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # T-Invest instrument identifiers.
    figi: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # e.g. SHARE, CURRENCY, FUTURES, INDEX...
    instrument_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    lot_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Instrument id={self.id} ticker={self.ticker!r}>"
