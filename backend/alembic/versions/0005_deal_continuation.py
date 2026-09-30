"""Live deal continuation tables (MVP-6.12).

Revision ID: 0005_deal_continuation
Revises: 0004_bot_deposit
Create Date: 2026-09-30

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005_deal_continuation"
down_revision: Union[str, None] = "0004_bot_deposit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_figi", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("deposit", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("base_nominal", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("reference_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("lot_size", sa.BigInteger(), nullable=True),
        sa.Column("tick_size", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("tp_percent", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("active_limit", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("average_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("tp_rev", sa.Integer(), nullable=False),
        sa.Column("tp_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("tp_quantity", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("tp_intent_id", sa.String(length=64), nullable=True),
        sa.Column("tp_order_id", sa.String(length=64), nullable=True),
        sa.Column("tp_broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deals_bot_id", "deals", ["bot_id"])

    op.create_table(
        "deal_levels",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("deal_id", sa.BigInteger(), nullable=False),
        sa.Column("level_index", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("nominal", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("offset_percent", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_market", sa.Boolean(), nullable=False),
        sa.Column("filled_quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("intent_id", sa.String(length=64), nullable=True),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deal_levels_deal_id", "deal_levels", ["deal_id"])


def downgrade() -> None:
    op.drop_index("ix_deal_levels_deal_id", table_name="deal_levels")
    op.drop_table("deal_levels")
    op.drop_index("ix_deals_bot_id", table_name="deals")
    op.drop_table("deals")
