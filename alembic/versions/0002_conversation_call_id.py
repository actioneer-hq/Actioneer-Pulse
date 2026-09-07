"""conversation.call_id (per-call chat threads)

Adds a nullable `call_id` to `conversation`: NULL = a global-chat thread, set = a per-call thread.
Runs per schema (see alembic/env.py). Plain column (no FK constraint) so the ALTER is dialect-simple
on both Postgres and SQLite; the ORM model carries the FK for fresh create_all builds.

Revision ID: 0002_conv_call_id
Revises: 0001_baseline
Create Date: 2026-09-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_conv_call_id"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("call_id", sa.String(36), nullable=True))
    op.create_index("ix_conversation_call", "conversation", ["call_id", "created_by"])


def downgrade() -> None:
    op.drop_index("ix_conversation_call", table_name="conversation")
    op.drop_column("conversation", "call_id")
