"""llm config roles: rename judge_config -> llm_config, add role + prompt.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("judge_config", "llm_config")
    with op.batch_alter_table("llm_config") as b:
        b.add_column(sa.Column("role", sa.String(32), nullable=False,
                               server_default="post_call_analysis"))
        b.add_column(sa.Column("prompt", sa.Text()))
    # existing rows are the post-call judge; the server_default already backfilled them.
    # swap the tenant-only unique for (tenant, role).
    with op.batch_alter_table("llm_config") as b:
        b.drop_constraint("uq_judge_config_tenant", type_="unique")
        b.create_unique_constraint("uq_llm_config_tenant_role", ["tenant_id", "role"])


def downgrade() -> None:
    with op.batch_alter_table("llm_config") as b:
        b.drop_constraint("uq_llm_config_tenant_role", type_="unique")
        b.create_unique_constraint("uq_judge_config_tenant", ["tenant_id"])
        b.drop_column("prompt")
        b.drop_column("role")
    op.rename_table("llm_config", "judge_config")
