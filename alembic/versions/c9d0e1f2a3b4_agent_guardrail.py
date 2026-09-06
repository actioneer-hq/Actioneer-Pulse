"""agent guardrails: versioned per-agent NLI rules (mirrors agent_script).

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_guardrail",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("prompt_id", sa.String(), sa.ForeignKey("prompt.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("app_user.id")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_guardrail_version"),
    )
    op.create_index("ix_agent_guardrail_active", "agent_guardrail", ["agent_id", "active"])


def downgrade() -> None:
    op.drop_index("ix_agent_guardrail_active", table_name="agent_guardrail")
    op.drop_table("agent_guardrail")
