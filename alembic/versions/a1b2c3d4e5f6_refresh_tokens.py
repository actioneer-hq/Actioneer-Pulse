"""refresh_token: revocable login sessions (JWT access + rotating refresh).

Revision ID: a1b2c3d4e5f6
Revises: 9c1a7b2e4d60
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "9c1a7b2e4d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_token",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_refresh_token_prefix", "refresh_token", ["token_prefix"])
    op.create_index("ix_refresh_token_user", "refresh_token", ["user_id"])
    op.create_index("ix_refresh_token_family", "refresh_token", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_token_family", table_name="refresh_token")
    op.drop_index("ix_refresh_token_user", table_name="refresh_token")
    op.drop_index("ix_refresh_token_prefix", table_name="refresh_token")
    op.drop_table("refresh_token")
