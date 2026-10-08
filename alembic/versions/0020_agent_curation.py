"""agent.curate_training_data: projects opt in to training-data curation.

Revision ID: 0020_agent_curation
Revises: 0019_moments
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020_agent_curation"
down_revision = "0019_moments"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)} if table in insp.get_table_names() else set()


def upgrade() -> None:
    cols = _cols("agent")
    if cols and "curate_training_data" not in cols:
        op.add_column("agent", sa.Column("curate_training_data", sa.Boolean(), nullable=False,
                                         server_default=sa.false()))


def downgrade() -> None:
    if "curate_training_data" in _cols("agent"):
        op.drop_column("agent", "curate_training_data")
