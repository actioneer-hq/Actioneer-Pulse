"""baseline: schema-per-tenant, no tenant_id

Greenfield baseline. Under schema-per-tenant each org lives in its own Postgres schema holding this
entire table set (no `tenant_id` column). Migrations run per schema (see alembic/env.py); on SQLite
there is a single flat schema. This baseline just builds the full model set in the target schema
(pgvector enabled first on Postgres), rather than replaying the old incremental history.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-07
"""

from __future__ import annotations

from alembic import op

from voiceobs.db.base import Base
from voiceobs.db import models  # noqa: F401 — register all tables on Base.metadata

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # search_path / target schema is set by env.py before this runs.
    Base.metadata.create_all(bind)


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
