"""transcript table — BYO transcript, one per call

Revision ID: 4d7f1b8e3a29
Revises: 2b5d8f3c1e07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d7f1b8e3a29"
down_revision: str | Sequence[str] | None = "2b5d8f3c1e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36), sa.ForeignKey("call.id"), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(32)),
        sa.Column("format", sa.String(24)),
        sa.Column("content", sa.Text()),
        sa.Column("uri", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", name="uq_transcript_call"),
    )
    op.create_index("ix_transcript_tenant_id", "transcript", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_transcript_tenant_id", table_name="transcript")
    op.drop_table("transcript")
