"""turn.llm_ttft_reported_ms + tts_ttfb_reported_ms — producer-reported latency

Revision ID: 3c6e9a4d2f18
Revises: 2b5d8f3c1e07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c6e9a4d2f18"
down_revision: str | Sequence[str] | None = "2b5d8f3c1e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turn", sa.Column("llm_ttft_reported_ms", sa.Float(), nullable=True))
    op.add_column("turn", sa.Column("tts_ttfb_reported_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("turn", "tts_ttfb_reported_ms")
    op.drop_column("turn", "llm_ttft_reported_ms")
