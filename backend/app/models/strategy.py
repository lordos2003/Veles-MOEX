"""Strategy domain models.

A Strategy is configuration/data, not user-written code (Architecture &
Product Specification section 3). StrategyVersion is a separate, immutable
entity so historical backtests can reference a specific, reproducible version.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow


class Strategy(TimestampMixin, Base):
    """A strategy configuration. Immutable history is kept in versions."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Structured strategy configuration (see spec section 3 blocks).
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    strategy_versions: Mapped[list[StrategyVersion]] = relationship(
        back_populates="strategy",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Strategy id={self.id} name={self.name!r}>"


class StrategyVersion(Base):
    """An immutable snapshot of a strategy configuration."""

    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("strategies.id"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    strategy: Mapped[Strategy] = relationship(back_populates="strategy_versions")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<StrategyVersion id={self.id} strategy={self.strategy_id} v={self.version}>"
