"""Instrument first-candle dates (MVP-7.6).

Revision ID: 0007_first_candle_dates
Revises: 0006_stop_loss
Create Date: 2026-10-09

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007_first_candle_dates"
down_revision: Union[str, None] = "0006_stop_loss"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MVP-7.6 H2: broker-reported start of candle history. NULL = the broker
    # has no such fact; existing rows stay NULL until the next sync.
    op.add_column(
        "instruments",
        sa.Column("first_1min_candle_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "instruments",
        sa.Column("first_1day_candle_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instruments", "first_1day_candle_date")
    op.drop_column("instruments", "first_1min_candle_date")
