"""tenant_settings table + Turn.interruption_probability / e2e_latency_ms

Revision ID: 6f9b3d0a5c22
Revises: 5e8a2c6f4b31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6f9b3d0a5c22"
down_revision: str | Sequence[str] | None = "5e8a2c6f4b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("audio_analysis_enabled", sa.Boolean()),  # null = global default
        sa.Column("audio_store_prefix", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_settings_tenant"),
    )
    op.create_index("ix_tenant_settings_tenant_id", "tenant_settings", ["tenant_id"])

    op.add_column("turn", sa.Column("interruption_probability", sa.Float()))
    op.add_column("turn", sa.Column("e2e_latency_ms", sa.Float()))


def downgrade() -> None:
    op.drop_column("turn", "e2e_latency_ms")
    op.drop_column("turn", "interruption_probability")
    op.drop_index("ix_tenant_settings_tenant_id", table_name="tenant_settings")
    op.drop_table("tenant_settings")
