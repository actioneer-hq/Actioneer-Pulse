"""judgment: failure-analysis fields (root cause, model fault, hallucination, fix).

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLS = [
    ("is_failure", sa.Boolean()),
    ("root_cause", sa.Text()),
    ("model_fault", sa.String(16)),
    ("model_fault_detail", sa.Text()),
    ("hallucination", sa.Boolean()),
    ("hallucination_detail", sa.Text()),
    ("suggested_fix", sa.Text()),
]


def upgrade() -> None:
    with op.batch_alter_table("judgment") as b:
        for name, col in _COLS:
            b.add_column(sa.Column(name, col))


def downgrade() -> None:
    with op.batch_alter_table("judgment") as b:
        for name, _ in reversed(_COLS):
            b.drop_column(name)
