"""moment.handled + moment.embed_model: unscripted moments split by whether the agent's reply worked,
and which embedding model/instruct produced each vector (a change re-embeds).

Revision ID: 0021_moment_handled
Revises: 0020_agent_curation
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021_moment_handled"
down_revision = "0020_agent_curation"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)} if table in insp.get_table_names() else set()


def upgrade() -> None:
    cols = _cols("moment")
    if cols and "handled" not in cols:
        op.add_column("moment", sa.Column("handled", sa.Boolean(), nullable=True))
    if cols and "embed_model" not in cols:
        op.add_column("moment", sa.Column("embed_model", sa.String(255), nullable=True))


def downgrade() -> None:
    for c in ("embed_model", "handled"):
        if c in _cols("moment"):
            op.drop_column("moment", c)
