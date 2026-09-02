"""turn.tts_cancelled — TTS aborted mid-synthesis (speech cut off)

Revision ID: 7a0c4e1b8d33
Revises: 6f9b3d0a5c22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7a0c4e1b8d33"
down_revision: str | Sequence[str] | None = "6f9b3d0a5c22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turn", sa.Column("tts_cancelled", sa.Boolean()))


def downgrade() -> None:
    op.drop_column("turn", "tts_cancelled")
