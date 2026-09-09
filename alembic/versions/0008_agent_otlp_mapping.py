"""agent_otlp_mapping: per-agent JSONata OTLP translation

One JSONata expression per agent, converting the producer's OTLP dialect into Pulse's canonical
Trace JSON (see frameworks/jsonata.py). Runs per schema (see alembic/env.py). Idempotent — the
create_all baseline already builds it on a fresh DB, so create only when missing.

Revision ID: 0008_agent_otlp_mapping
Revises: 0007_conv_audio_native
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_agent_otlp_mapping"
down_revision = "0007_conv_audio_native"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("agent_otlp_mapping"):
        return
    op.create_table(
        "agent_otlp_mapping",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("agent_id", name="uq_agent_otlp_mapping_agent"),
    )


def downgrade() -> None:
    op.drop_table("agent_otlp_mapping")
