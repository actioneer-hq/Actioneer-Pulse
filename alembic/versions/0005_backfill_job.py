"""backfill_job: user-triggered blob backfill jobs

A persistent job row per backfill (survives restart, resumable, powers the Failed section +
notify-on-complete). Runs per schema (see alembic/env.py). Idempotent — the create_all baseline
already builds it on a fresh DB, so create only when missing.

Revision ID: 0005_backfill_job
Revises: 0004_call_provenance
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_backfill_job"
down_revision = "0004_call_provenance"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("backfill_job"):
        return
    op.create_table(
        "backfill_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(64)),
        sa.Column("agent_id", sa.String(36)),
        sa.Column("source", sa.String(16), nullable=False, server_default="audio"),
        sa.Column("options", sa.JSON()),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("phase", sa.String(32)),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_backfill_status", "backfill_job", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_backfill_status", table_name="backfill_job")
    op.drop_table("backfill_job")
