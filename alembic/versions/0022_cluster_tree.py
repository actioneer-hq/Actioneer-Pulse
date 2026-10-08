"""moment_cluster as a tree: parent_key, depth, is_leaf, medoid, description, placement.

Unscripted moments cluster hierarchically (HDBSCAN inside each cluster, up to depth 5); leaves carry the
medoid moment's description and where they belong in the script journey (decision model).

Revision ID: 0022_cluster_tree
Revises: 0021_moment_handled
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022_cluster_tree"
down_revision = "0021_moment_handled"
branch_labels = None
depends_on = None

_COLS = (
    ("parent_key", sa.Integer(), None),
    ("depth", sa.Integer(), sa.text("0")),
    ("is_leaf", sa.Boolean(), sa.true()),
    ("medoid_moment_id", sa.String(36), None),
    ("description", sa.Text(), None),
    ("placement", sa.JSON(), None),
)


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)} if table in insp.get_table_names() else set()


def upgrade() -> None:
    cols = _cols("moment_cluster")
    for name, typ, default in _COLS:
        if cols and name not in cols:
            op.add_column("moment_cluster", sa.Column(name, typ, nullable=default is None,
                                                      server_default=default))


def downgrade() -> None:
    for name, _, _ in reversed(_COLS):
        if name in _cols("moment_cluster"):
            op.drop_column("moment_cluster", name)
