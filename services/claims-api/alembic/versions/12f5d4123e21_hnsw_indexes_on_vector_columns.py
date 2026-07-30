"""hnsw indexes on vector columns

Revision ID: 12f5d4123e21
Revises: 27076aeb634f
Create Date: 2026-07-29 02:48:20.570232

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "12f5d4123e21"
down_revision: str | Sequence[str] | None = "27076aeb634f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "CREATE INDEX ix_policy_chunks_embedding_hnsw "
        "ON ai.policy_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX ix_claim_precedents_embedding_hnsw "
        "ON ai.claim_precedents USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ai.ix_claim_precedents_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ai.ix_policy_chunks_embedding_hnsw")
