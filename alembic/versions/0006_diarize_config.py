"""agent_audio_config: BYO diarization endpoint (diarize_base_url, diarize_model, diarize_key_ciphertext)

For mixed/mono recordings that need speaker separation. Runs per schema (see alembic/env.py).
Idempotent — the create_all baseline already builds these on a fresh DB, so only add what's missing.

Revision ID: 0006_diarize_config
Revises: 0005_backfill_job
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_diarize_config"
down_revision = "0005_backfill_job"
branch_labels = None
depends_on = None

_ADD = [
    ("diarize_base_url", sa.String(512)),
    ("diarize_model", sa.String(128)),
    ("diarize_key_ciphertext", sa.Text()),
]


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols("agent_audio_config")
    with op.batch_alter_table("agent_audio_config") as b:
        for name, type_ in _ADD:
            if name not in have:
                b.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_audio_config") as b:
        for col in ["diarize_key_ciphertext", "diarize_model", "diarize_base_url"]:
            b.drop_column(col)
