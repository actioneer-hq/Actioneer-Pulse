"""call: analysis provenance (analysis_mode, audio_layout, diarization_confidence, analysis_error)

Adds provenance so audio-only / backfilled calls are distinguishable from live full-fidelity calls and
can be segmented in the boards. Runs per schema (see alembic/env.py). Idempotent — the create_all
baseline already builds these on a fresh DB, so only add what's missing.

Revision ID: 0004_call_provenance
Revises: 0003_storage_descriptor
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_call_provenance"
down_revision = "0003_storage_descriptor"
branch_labels = None
depends_on = None

_ADD = [
    ("analysis_mode", sa.String(24), "full"),  # server_default so existing rows read as 'full'
    ("audio_layout", sa.String(16), None),
    ("diarization_confidence", sa.Float(), None),
    ("analysis_error", sa.Text(), None),
]


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols("call")
    with op.batch_alter_table("call") as b:
        for name, type_, default in _ADD:
            if name not in have:
                b.add_column(sa.Column(name, type_, nullable=True, server_default=default))


def downgrade() -> None:
    with op.batch_alter_table("call") as b:
        for col in ["analysis_error", "diarization_confidence", "audio_layout", "analysis_mode"]:
            b.drop_column(col)
