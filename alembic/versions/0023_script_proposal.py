"""script_proposal: script-improvement runs (improved journeys + rendered scripts + diffs).

Revision ID: 0023_script_proposal
Revises: 0022_cluster_tree
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023_script_proposal"
down_revision = "0022_cluster_tree"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "agent" in _tables() and "script_proposal" not in _tables():
        op.create_table(
            "script_proposal",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("agent_id", sa.String(36), nullable=False, index=True),
            sa.Column("prompt_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("approved_variant", sa.String(16), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if "script_proposal" in _tables():
        op.drop_table("script_proposal")
