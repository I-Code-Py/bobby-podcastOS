"""payment hold, clipper payment link, usd/eur rate

Revision ID: 002_payment_hold
Revises: 001_initial
Create Date: 2025-01-02 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "002_payment_hold"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payout_lines", sa.Column("held", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("payout_lines", sa.Column("hold_note", sa.Text, nullable=True))
    op.add_column("clippers", sa.Column("payment_link", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("payout_lines", "held")
    op.drop_column("payout_lines", "hold_note")
    op.drop_column("clippers", "payment_link")
