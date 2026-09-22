"""Durable live execution state tables.

Revision ID: 0003_live_execution_state
Revises: 0002_instrument_fields_and_market_candles
Create Date: 2026-09-22

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_live_execution_state"
down_revision: Union[str, None] = "0002_instrument_fields_and_market_candles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_intents",
        sa.Column("intent_id", sa.String(length=64), nullable=False),
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_figi", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("intent_id"),
    )

    op.create_table(
        "live_orders",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("intent_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_figi", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("filled_quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("average_fill_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reject_info", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index("ix_live_orders_intent_id", "live_orders", ["intent_id"])
    op.create_index("ix_live_orders_idempotency_key", "live_orders", ["idempotency_key"])
    op.create_index("ix_live_orders_broker_order_id", "live_orders", ["broker_order_id"])

    op.create_table(
        "live_fills",
        sa.Column("fill_id", sa.String(length=64), nullable=False),
        sa.Column("internal_order_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("fee", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("broker_execution_id", sa.String(length=64), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("fill_id"),
    )
    op.create_index("ix_live_fills_internal_order_id", "live_fills", ["internal_order_id"])

    op.create_table(
        "live_positions",
        sa.Column("instrument_figi", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("average_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("fees", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("instrument_figi"),
    )


def downgrade() -> None:
    op.drop_table("live_positions")
    op.drop_index("ix_live_fills_internal_order_id", table_name="live_fills")
    op.drop_table("live_fills")
    op.drop_index("ix_live_orders_broker_order_id", table_name="live_orders")
    op.drop_index("ix_live_orders_idempotency_key", table_name="live_orders")
    op.drop_index("ix_live_orders_intent_id", table_name="live_orders")
    op.drop_table("live_orders")
    op.drop_table("live_intents")
