"""claim number sequence

Revision ID: 8ca807d5992d
Revises: b19572c9d097
Create Date: 2026-07-28 14:05:59.451425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ca807d5992d'
down_revision: Union[str, Sequence[str], None] = 'b19572c9d097'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SEQUENCE claims.claim_number_seq START WITH 1 INCREMENT BY 1")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP SEQUENCE claims.claim_number_seq")
