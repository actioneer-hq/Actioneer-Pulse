"""agent_integration_manifest: the wizard's integration manifest, stored per agent

The Pulse wizard's `register-integration` PUTs one JSON manifest per agent (storage
selectors + decoders + JSONata mappers); the manifest runtime executes it during
`source=manifest` backfills. Runs per schema (see alembic/env.py). Idempotent.

Revision ID: 0013_agent_integration_manifest
Revises: 0012_event_position
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_agent_integration_manifest"
down_revision = "0012_event_position"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table("agent_integration_manifest"):
        op.create_table(
            "agent_integration_manifest",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("agent_id", name="uq_agent_integration_manifest_agent"),
        )


def downgrade() -> None:
    if _has_table("agent_integration_manifest"):
        op.drop_table("agent_integration_manifest")
