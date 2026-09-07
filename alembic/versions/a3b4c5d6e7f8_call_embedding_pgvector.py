"""call_embedding + pgvector: semantic-clustering source vectors.

Enables the pgvector extension and creates the call_embedding table. The embedding column is a real
`vector` on Postgres and a float32 blob on SQLite (dev/tests). The fixed-dim HNSW index is added
later, in the similarity-search phase.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from pgvector.sqlalchemy import Vector
        emb_type: sa.types.TypeEngine = Vector()
    else:
        emb_type = sa.LargeBinary()

    op.create_table(
        "call_embedding",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), sa.ForeignKey("call.id"), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("embedding", emb_type, nullable=False),
        sa.Column("model", sa.String(128)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id", "field", name="uq_call_embedding"),
    )
    op.create_index("ix_call_embedding_tenant_field", "call_embedding", ["tenant_id", "field"])


def downgrade() -> None:
    op.drop_index("ix_call_embedding_tenant_field", table_name="call_embedding")
    op.drop_table("call_embedding")
    # leave the vector extension in place — other objects may depend on it.
