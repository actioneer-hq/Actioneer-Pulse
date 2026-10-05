"""call.template_sha256: the prompt version stays on the call.

The hash is stamped from the trace. Linking prompt_id still needs the registered
text, but comparison can group calls before that text arrives. Runs per schema
(see alembic/env.py). Idempotent.

Revision ID: 0016_call_template_sha256
Revises: 0015_clusters_per_agent
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016_call_template_sha256"
down_revision = "0015_clusters_per_agent"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _cols("call")
    if cols and "template_sha256" not in cols:
        op.add_column("call", sa.Column("template_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    if "template_sha256" in _cols("call"):
        op.drop_column("call", "template_sha256")
