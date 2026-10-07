"""agent_journey + judgment.journey: the journey judge's storage.

agent_journey holds the journey extracted from each script version (keyed by prompt);
judgment.journey holds the per-call journey judgment. Runs per schema (see alembic/env.py).
Idempotent.

Revision ID: 0017_agent_journey
Revises: 0016_call_template_sha256
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017_agent_journey"
down_revision = "0016_call_template_sha256"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "prompt" in _tables() and "agent_journey" not in _tables():
        op.create_table(
            "agent_journey",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("prompt_id", sa.String(36), sa.ForeignKey("prompt.id"), nullable=False, unique=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("journey", sa.JSON(), nullable=True),
            sa.Column("draft", sa.JSON(), nullable=True),
            sa.Column("model", sa.String(64), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    cols = _cols("judgment")
    if cols and "journey" not in cols:
        op.add_column("judgment", sa.Column("journey", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "journey" in _cols("judgment"):
        op.drop_column("judgment", "journey")
    if "agent_journey" in _tables():
        op.drop_table("agent_journey")
