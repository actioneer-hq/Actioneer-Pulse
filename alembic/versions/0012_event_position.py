"""event.position: the canonical ordering key for the span/event timeline

Ordering is the universal concept; time is merely its best source (CONTRACTS.md §5).
The worker stamps a dense per-call position at persist (core.calculator.order_key:
clock when known, source `sequence` when not), so reads order by position and
`t_offset_s` goes back to being a pure timing fact. Pre-existing rows keep NULL and
fall back to t_offset_s ordering; they heal on the next metric_version re-analysis.
Runs per schema (see alembic/env.py). Idempotent.

Revision ID: 0012_event_position
Revises: 0011_agent_call_params
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_event_position"
down_revision = "0011_agent_call_params"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "position" not in _cols("event"):
        with op.batch_alter_table("event") as b:
            b.add_column(sa.Column("position", sa.Integer(), nullable=True))


def downgrade() -> None:
    if "position" in _cols("event"):
        with op.batch_alter_table("event") as b:
            b.drop_column("position")
