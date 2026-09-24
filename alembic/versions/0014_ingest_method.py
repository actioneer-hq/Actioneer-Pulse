"""agent_integration_manifest: ingest_method + last_polled_modified

Adds the ingest routing method (telemetry_ingest_event | storage_polling |
not_applicable_no_logs) and the storage-poller watermark to the manifest row. Runs per
schema (see alembic/env.py). Idempotent.

Revision ID: 0014_ingest_method
Revises: 0013_agent_integration_manifest
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_ingest_method"
down_revision = "0013_agent_integration_manifest"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _columns("agent_integration_manifest")
    if not cols:
        return  # table not created yet in this schema
    if "ingest_method" not in cols:
        op.add_column(
            "agent_integration_manifest",
            sa.Column("ingest_method", sa.String(32), nullable=False,
                      server_default="storage_polling"),
        )
    if "last_polled_modified" not in cols:
        op.add_column(
            "agent_integration_manifest",
            sa.Column("last_polled_modified", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    cols = _columns("agent_integration_manifest")
    if "last_polled_modified" in cols:
        op.drop_column("agent_integration_manifest", "last_polled_modified")
    if "ingest_method" in cols:
        op.drop_column("agent_integration_manifest", "ingest_method")
