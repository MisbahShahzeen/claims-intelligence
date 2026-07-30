"""claim number sequence

Revision ID: 8ca807d5992d
Revises: b19572c9d097
Create Date: 2026-07-28 14:05:59.451425

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8ca807d5992d"
down_revision: str | Sequence[str] | None = "b19572c9d097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SEQUENCE claims.claim_number_seq START WITH 1 INCREMENT BY 1")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP SEQUENCE claims.claim_number_seq")
