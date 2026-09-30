"""Bot deposit (MVP-6.11 C5).

Revision ID: 0004_bot_deposit
Revises: 0003_live_execution_state
Create Date: 2026-09-29

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004_bot_deposit"
down_revision: Union[str, None] = "0003_live_execution_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("deposit", sa.Numeric(precision=20, scale=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bots", "deposit")
