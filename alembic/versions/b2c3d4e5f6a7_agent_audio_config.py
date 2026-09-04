"""agent_audio_config: per-agent S3 audio-analysis config (pull path).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_audio_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("enabled", sa.Boolean()),
        sa.Column("s3_bucket", sa.String(255)),
        sa.Column("s3_prefix", sa.String(1024)),
        sa.Column("s3_region", sa.String(64)),
        sa.Column("s3_endpoint_url", sa.String(512)),
        sa.Column("access_key_id", sa.String(128)),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", name="uq_agent_audio_config_agent"),
    )


def downgrade() -> None:
    op.drop_table("agent_audio_config")
