"""upload_blob: file onboarding uploads (manifest + call audio) stored in the DB, not on a disk
the api and workers would have to share.

Revision ID: 0024_upload_blob
Revises: 0023_script_proposal
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_upload_blob"
down_revision = "0023_script_proposal"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "agent" in _tables() and "upload_blob" not in _tables():
        op.create_table(
            "upload_blob",
            sa.Column("key", sa.String(1024), primary_key=True),
            sa.Column("data", sa.LargeBinary(), nullable=False),
            sa.Column("bytes", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    if "upload_blob" in _tables():
        op.drop_table("upload_blob")
