"""judge_config + judgment tables

Revision ID: 5e8a2c6f4b31
Revises: 4d7f1b8e3a29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e8a2c6f4b31"
down_revision: str | Sequence[str] | None = "4d7f1b8e3a29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "judge_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.String(512)),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("params", sa.JSON()),
        sa.Column("enabled", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_judge_config_tenant"),
    )
    op.create_index("ix_judge_config_tenant_id", "judge_config", ["tenant_id"])

    op.create_table(
        "judgment",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36), sa.ForeignKey("call.id"), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("disposition", sa.String(32)),
        sa.Column("status", sa.String(16)),
        sa.Column("model", sa.String(128)),
        sa.Column("error", sa.Text()),
        sa.Column("sentiment", sa.String(16)),
        sa.Column("objective_achieved", sa.String(16)),
        sa.Column("answered_by", sa.String(16)),
        sa.Column("primary_language", sa.String(32)),
        sa.Column("secondary_languages", sa.JSON()),
        sa.Column("script_adherence", sa.String(16)),
        sa.Column("escalation_requested", sa.Boolean()),
        sa.Column("callback_requested", sa.Boolean()),
        sa.Column("callback_time", sa.String(128)),
        sa.Column("summary", sa.Text()),
        sa.Column("judged_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", name="uq_judgment_call"),
    )
    op.create_index("ix_judgment_tenant_id", "judgment", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_judgment_tenant_id", table_name="judgment")
    op.drop_table("judgment")
    op.drop_index("ix_judge_config_tenant_id", table_name="judge_config")
    op.drop_table("judge_config")
