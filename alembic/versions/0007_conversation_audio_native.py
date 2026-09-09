"""conversation: per-chat audio_native_enabled toggle

Per-conversation opt-in for the chat agents' audio-native tool (default off). Runs per schema (see
alembic/env.py). Idempotent — the create_all baseline already builds it on a fresh DB.

Revision ID: 0007_conv_audio_native
Revises: 0006_diarize_config
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_conv_audio_native"
down_revision = "0006_diarize_config"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "audio_native_enabled" not in _cols("conversation"):
        with op.batch_alter_table("conversation") as b:
            b.add_column(sa.Column("audio_native_enabled", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("conversation") as b:
        b.drop_column("audio_native_enabled")
