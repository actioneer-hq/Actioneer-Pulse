"""drop llm_config: per-role LLM config moves to config.py + env (no per-tenant DB config).

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("llm_config")


def downgrade() -> None:
    op.create_table(
        "llm_config",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="post_call_analysis"),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.String(512)),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt", sa.Text()),
        sa.Column("params", sa.JSON()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "role", name="uq_llm_config_tenant_role"),
    )
