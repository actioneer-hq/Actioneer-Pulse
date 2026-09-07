"""cluster + call_cluster: per-lever semantic clusters and per-call assignments.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cluster",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("lever", sa.String(32), nullable=False),
        sa.Column("cluster_key", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text()),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "lever", "cluster_key", name="uq_cluster"),
    )
    op.create_table(
        "call_cluster",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), sa.ForeignKey("call.id"), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("lever", sa.String(32), nullable=False),
        sa.Column("cluster_key", sa.Integer()),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id", "lever", name="uq_call_cluster"),
    )
    op.create_index("ix_call_cluster_tenant_lever", "call_cluster", ["tenant_id", "lever"])


def downgrade() -> None:
    op.drop_index("ix_call_cluster_tenant_lever", table_name="call_cluster")
    op.drop_table("call_cluster")
    op.drop_table("cluster")
