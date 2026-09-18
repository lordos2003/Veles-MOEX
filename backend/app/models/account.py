"""Account domain model.

Represents a broker account bound to the platform. Broker-specific connection
details (API token, credentials) must not be stored here in plain text; secrets
belong to a broker credentials source outside the source tree.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Account(TimestampMixin, Base):
    """A broker account available to the platform."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Broker implementation key, e.g. "tinvest". Single broker for now.
    broker: Mapped[str] = mapped_column(String(32), nullable=False)
    # External account id as returned by the broker.
    external_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Account id={self.id} name={self.name!r} broker={self.broker!r}>"
