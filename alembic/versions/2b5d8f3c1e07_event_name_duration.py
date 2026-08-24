"""event.name + event.duration_s — a waterfall needs a bar length and a label

Revision ID: 2b5d8f3c1e07
Revises: 1a4c7e2b9f31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2b5d8f3c1e07"
down_revision: str | Sequence[str] | None = "1a4c7e2b9f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("event", sa.Column("name", sa.String(64), nullable=True))
    op.add_column("event", sa.Column("duration_s", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("event", "duration_s")
    op.drop_column("event", "name")
