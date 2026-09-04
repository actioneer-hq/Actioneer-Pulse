"""audio_discrepancy: ground-truth vs reported findings per call.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audio_discrepancy",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36), sa.ForeignKey("call.id"), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("turn_index", sa.Integer()),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("reported", sa.Text()),
        sa.Column("measured", sa.Text()),
        sa.Column("delta", sa.Float()),
        sa.Column("band", sa.Float()),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audio_discrepancy_call", "audio_discrepancy", ["call_id"])


def downgrade() -> None:
    op.drop_index("ix_audio_discrepancy_call", table_name="audio_discrepancy")
    op.drop_table("audio_discrepancy")
