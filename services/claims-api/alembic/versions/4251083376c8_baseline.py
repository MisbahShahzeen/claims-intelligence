"""baseline

Revision ID: 4251083376c8
Revises:
Create Date: 2026-07-28 13:07:14.196760

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "4251083376c8"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
