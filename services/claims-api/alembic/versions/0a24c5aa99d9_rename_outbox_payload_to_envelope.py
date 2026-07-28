"""rename outbox payload to envelope

Revision ID: 0a24c5aa99d9
Revises: ed4defe2f2c6
Create Date: 2026-07-28 22:27:31.480499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a24c5aa99d9'
down_revision: Union[str, Sequence[str], None] = 'ed4defe2f2c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("outbox", "payload", new_column_name="envelope", schema="claims")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("outbox", "envelope", new_column_name="payload", schema="claims")
