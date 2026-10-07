"""Journey stages 2-3: judgment.enrich_status / curate_status + training_sample.

Stage 2 (LLM enrichment) and stage 3 (training-data curation) run after the decision model, tracked on
the judgment; curated corrections live in training_sample. Runs per schema (see alembic/env.py).
Idempotent.

Revision ID: 0018_journey_stages
Revises: 0017_agent_journey
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018_journey_stages"
down_revision = "0017_agent_journey"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    cols = _cols("judgment")
    for name in ("enrich_status", "curate_status"):
        if cols and name not in cols:
            op.add_column("judgment", sa.Column(name, sa.String(16), nullable=True))
    if "call" in _tables() and "training_sample" not in _tables():
        op.create_table(
            "training_sample",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("call_id", sa.String(36), sa.ForeignKey("call.id"), nullable=False, index=True),
            sa.Column("prompt_id", sa.String(36), nullable=True),
            sa.Column("turn", sa.Integer(), nullable=False),
            sa.Column("item", sa.Text(), nullable=False),
            sa.Column("failure_kind", sa.String(16), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False, server_default="response"),
            sa.Column("observed", sa.Text(), nullable=False),
            sa.Column("corrected", sa.Text(), nullable=False),
            sa.Column("corrected_tool", sa.String(128), nullable=True),
            sa.Column("corrected_args", sa.JSON(), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("model", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.UniqueConstraint("call_id", "turn", "item", name="uq_training_sample"),
        )


def downgrade() -> None:
    if "training_sample" in _tables():
        op.drop_table("training_sample")
    for name in ("curate_status", "enrich_status"):
        if name in _cols("judgment"):
            op.drop_column("judgment", name)
