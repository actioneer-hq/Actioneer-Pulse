"""agent_audio_config: add BYO STT columns for transcript verification.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_audio_config") as b:
        b.add_column(sa.Column("stt_base_url", sa.String(512)))
        b.add_column(sa.Column("stt_model", sa.String(128)))
        b.add_column(sa.Column("stt_key_ciphertext", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("agent_audio_config") as b:
        b.drop_column("stt_key_ciphertext")
        b.drop_column("stt_model")
        b.drop_column("stt_base_url")
