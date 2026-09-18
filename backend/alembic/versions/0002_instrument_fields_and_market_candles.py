"""Instrument domain fields and market candles.

Revision ID: 0002_instrument_fields_and_market_candles
Revises: 0001_initial
Create Date: 2026-09-18

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_instrument_fields_and_market_candles"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Instruments: add trading_status / exchange, make figi not-null and indexed.
    op.add_column("instruments", sa.Column("trading_status", sa.String(length=32), nullable=False))
    op.add_column("instruments", sa.Column("exchange", sa.String(length=32), nullable=True))
    op.alter_column(
        "instruments",
        "figi",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_index("ix_instruments_figi", "instruments", ["figi"])

    op.create_table(
        "market_candles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("figi", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("figi", "timeframe", "timestamp", name="uq_market_candles_figi_tf_ts"),
    )
    op.create_index("ix_market_candles_figi", "market_candles", ["figi"])


def downgrade() -> None:
    op.drop_index("ix_market_candles_figi", table_name="market_candles")
    op.drop_table("market_candles")
    op.drop_index("ix_instruments_figi", table_name="instruments")
    op.drop_column("instruments", "exchange")
    op.drop_column("instruments", "trading_status")
