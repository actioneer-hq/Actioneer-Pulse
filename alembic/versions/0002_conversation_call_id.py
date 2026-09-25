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
    # Idempotent: the create_all baseline already builds current-model columns on a fresh DB.
    insp = sa.inspect(op.get_bind())
    if "call_id" not in {c["name"] for c in insp.get_columns("conversation")}:
        op.add_column("conversation", sa.Column("call_id", sa.String(36), nullable=True))
    if "ix_conversation_call" not in {i["name"] for i in insp.get_indexes("conversation")}:
        op.create_index("ix_conversation_call", "conversation", ["call_id", "created_by"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "ix_conversation_call" in {i["name"] for i in insp.get_indexes("conversation")}:
        op.drop_index("ix_conversation_call", table_name="conversation")
    if "call_id" in {c["name"] for c in insp.get_columns("conversation")}:
        # batch mode rebuilds the table on SQLite — a bare DROP COLUMN fails there because a
        # foreign-key definition references call_id ("unknown column in foreign key definition").
        with op.batch_alter_table("conversation") as b:
            b.drop_column("call_id")
