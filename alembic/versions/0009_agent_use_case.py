"""agent: use_case metadata

A short, non-identifying market use-case for the agent, set by the onboarding wizard. Runs per schema
(see alembic/env.py). Idempotent — the create_all baseline already builds it on a fresh DB.

Revision ID: 0009_agent_use_case
Revises: 0008_agent_otlp_mapping
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_agent_use_case"
down_revision = "0008_agent_otlp_mapping"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "use_case" not in _cols("agent"):
        with op.batch_alter_table("agent") as b:
            b.add_column(sa.Column("use_case", sa.String(160), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent") as b:
        b.drop_column("use_case")
