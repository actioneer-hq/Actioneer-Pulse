"""judgment: llm_corrections

Per-turn corrected agent actions produced by the failure-analysis LLM (only when model_fault is
llm) — the raw material for SFT/DPO training data. A nullable JSON column. Runs per schema (see
alembic/env.py). Idempotent — the create_all baseline already builds it on a fresh DB.

Revision ID: 0010_judgment_llm_corrections
Revises: 0009_agent_use_case
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_judgment_llm_corrections"
down_revision = "0009_agent_use_case"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "llm_corrections" not in _cols("judgment"):
        with op.batch_alter_table("judgment") as b:
            b.add_column(sa.Column("llm_corrections", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("judgment") as b:
        b.drop_column("llm_corrections")
