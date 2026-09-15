"""call params: per-call template parameters + upload list + agent gating toggle

Per-agent CSV of per-call prompt-template values (keyed by call id), gating the post-call LLM
analysis. Runs per schema (see alembic/env.py). Idempotent — the create_all baseline builds the
tables/column on a fresh DB, so create/add only when missing.

Revision ID: 0011_agent_call_params
Revises: 0010_judgment_llm_corrections
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_agent_call_params"
down_revision = "0010_judgment_llm_corrections"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "params_required" not in _cols("agent"):
        with op.batch_alter_table("agent") as b:
            b.add_column(sa.Column("params_required", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))

    if not _has_table("agent_params_upload"):
        op.create_table(
            "agent_params_upload",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
            sa.Column("label", sa.String(160)),
            sa.Column("key_column", sa.String(64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_agent_params_upload_agent", "agent_params_upload", ["agent_id"])

    if not _has_table("call_params"):
        op.create_table(
            "call_params",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
            sa.Column("call_key", sa.String(128), nullable=False),
            sa.Column("params", sa.JSON(), nullable=False),
            sa.Column("upload_id", sa.String(36), sa.ForeignKey("agent_params_upload.id")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("agent_id", "call_key", name="uq_call_params_agent_key"),
        )


def downgrade() -> None:
    op.drop_table("call_params")
    op.drop_table("agent_params_upload")
    with op.batch_alter_table("agent") as b:
        b.drop_column("params_required")
