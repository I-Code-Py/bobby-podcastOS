"""add clipper payment method + handle

Revision ID: a1b2c3d4e5f6
Revises: 6286b547f27f
Create Date: 2026-07-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '6286b547f27f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('clippers', sa.Column('payment_method', sa.String(length=20), nullable=True))
    op.add_column('clippers', sa.Column('payment_handle', sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clippers', 'payment_handle')
    op.drop_column('clippers', 'payment_method')
