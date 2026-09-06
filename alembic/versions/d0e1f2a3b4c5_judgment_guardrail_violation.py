"""judgment: guardrail_violation (+ points), populated by the post-call judge.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("judgment") as b:
        b.add_column(sa.Column("guardrail_violation", sa.Boolean()))
        b.add_column(sa.Column("guardrail_violation_points", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("judgment") as b:
        b.drop_column("guardrail_violation_points")
        b.drop_column("guardrail_violation")
