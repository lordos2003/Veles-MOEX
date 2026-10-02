"""Simple stop-loss columns (MVP-6.16).

Revision ID: 0006_stop_loss
Revises: 0005_deal_continuation
Create Date: 2026-10-02

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_stop_loss"
down_revision: Union[str, None] = "0005_deal_continuation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MVP-6.16 E1/E2: Deal stop-loss state + close reason.
    op.add_column(
        "deals",
        sa.Column("sl_percent", sa.Numeric(precision=10, scale=4), nullable=True),
    )
    # Existing rows: no stop config -> the stop columns keep their defaults
    # (server_default fills pre-existing rows; the Python-side defaults on the
    # model mirror them for new rows).
    op.add_column(
        "deals",
        sa.Column(
            "sl_offset",
            sa.Numeric(precision=20, scale=8),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "deals",
        sa.Column(
            "p0_price", sa.Numeric(precision=20, scale=8), nullable=True
        ),
    )
    op.add_column(
        "deals",
        sa.Column(
            "sl_rev", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column("deals", sa.Column("sl_order_id", sa.String(length=64), nullable=True))
    op.add_column(
        "deals",
        sa.Column("sl_quantity", sa.Numeric(precision=20, scale=8), nullable=True),
    )
    op.add_column(
        "deals",
        sa.Column("sl_price", sa.Numeric(precision=20, scale=8), nullable=True),
    )
    op.add_column("deals", sa.Column("close_reason", sa.String(length=32), nullable=True))
    # MVP-6.16 E3: persisted per-Deal bot-stop choice (None is refused at START).
    op.add_column("deals", sa.Column("stop_bot_after", sa.Boolean(), nullable=True))

    # MVP-6.16 E3: the reason a bot was stopped after a stop close.
    op.add_column(
        "bots",
        sa.Column("stop_reason", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bots", "stop_reason")
    op.drop_column("deals", "stop_bot_after")
    op.drop_column("deals", "close_reason")
    op.drop_column("deals", "sl_price")
    op.drop_column("deals", "sl_quantity")
    op.drop_column("deals", "sl_order_id")
    op.drop_column("deals", "sl_rev")
    op.drop_column("deals", "p0_price")
    op.drop_column("deals", "sl_offset")
    op.drop_column("deals", "sl_percent")
