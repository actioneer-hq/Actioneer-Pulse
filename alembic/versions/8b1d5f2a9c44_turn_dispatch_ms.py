"""turn.dispatch_ms — first token -> TTS provider request

Revision ID: 8b1d5f2a9c44
Revises: 7a0c4e1b8d33
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b1d5f2a9c44"
down_revision: str | Sequence[str] | None = "7a0c4e1b8d33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turn", sa.Column("dispatch_ms", sa.Float()))


def downgrade() -> None:
    op.drop_column("turn", "dispatch_ms")
