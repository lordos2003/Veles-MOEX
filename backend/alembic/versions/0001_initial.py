"""Initial schema: core domain tables for the Veles-MOEX framework.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-18

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("figi", sa.String(length=64), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("instrument_type", sa.String(length=32), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("lot_size", sa.BigInteger(), nullable=True),
        sa.Column("tick_size", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("figi"),
    )
    op.create_index("ix_instruments_ticker", "instruments", ["ticker"])
    op.create_table(
        "strategies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", "version"),
    )
    op.create_index("ix_strategy_versions_strategy_id", "strategy_versions", ["strategy_id"])
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("type", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("filled_quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_external_id", "orders", ["external_id"])
    op.create_index("ix_orders_account_id", "orders", ["account_id"])
    op.create_index("ix_orders_instrument_id", "orders", ["instrument_id"])
    op.create_table(
        "executions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("commission", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_executions_order_id", "executions", ["order_id"])
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("average_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("fees", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_positions_account_id", "positions", ["account_id"])
    op.create_index("ix_positions_instrument_id", "positions", ["instrument_id"])
    op.create_table(
        "bots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("strategy_version_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bots_strategy_version_id", "bots", ["strategy_version_id"])
    op.create_index("ix_bots_account_id", "bots", ["account_id"])
    op.create_index("ix_bots_instrument_id", "bots", ["instrument_id"])


def downgrade() -> None:
    op.drop_index("ix_bots_instrument_id", table_name="bots")
    op.drop_index("ix_bots_account_id", table_name="bots")
    op.drop_index("ix_bots_strategy_version_id", table_name="bots")
    op.drop_table("bots")
    op.drop_index("ix_positions_instrument_id", table_name="positions")
    op.drop_index("ix_positions_account_id", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_executions_order_id", table_name="executions")
    op.drop_table("executions")
    op.drop_index("ix_orders_instrument_id", table_name="orders")
    op.drop_index("ix_orders_account_id", table_name="orders")
    op.drop_index("ix_orders_external_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_strategy_versions_strategy_id", table_name="strategy_versions")
    op.drop_table("strategy_versions")
    op.drop_table("strategies")
    op.drop_index("ix_instruments_ticker", table_name="instruments")
    op.drop_table("instruments")
    op.drop_table("accounts")
