"""MarketCandle domain model.

Persisted historical candles. The natural unique key for a candle is the tuple
(FIGI, timeframe, timestamp); the database enforces it so a synchronized candle
can only be stored once.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MarketCandle(TimestampMixin, Base):
    """A stored OHLCV candle."""

    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("figi", "timeframe", "timestamp", name="uq_market_candles_figi_tf_ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    figi: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Internal Timeframe enum value (e.g. "1m", "1h", "1d").
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    is_complete: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<MarketCandle figi={self.figi!r} tf={self.timeframe!r} ts={self.timestamp}>"
