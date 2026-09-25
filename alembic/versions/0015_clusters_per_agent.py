"""clusters per-agent: add agent_id to cluster + call_cluster; rescope uq_cluster

Clustering becomes per-agent (was org-wide). `cluster.cluster_key` is now unique within
(agent_id, lever), and call_cluster carries the call's agent_id for agent-scoped filtering.
Existing cluster rows are wiped — the next clustering run rebuilds them per-agent. Runs per
schema (see alembic/env.py). Idempotent.

Revision ID: 0015_clusters_per_agent
Revises: 0014_ingest_method
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_clusters_per_agent"
down_revision = "0014_ingest_method"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    # cluster keys change meaning (now per-agent) — clear stale rows; the worker rebuilds them.
    if "cluster" in sa.inspect(bind).get_table_names():
        op.execute("DELETE FROM call_cluster")
        op.execute("DELETE FROM cluster")

    # server_default="" satisfies the NOT NULL for the add-column backfill; app rows always set
    # agent_id explicitly (SQLite can't DROP DEFAULT, so we just leave the harmless default).
    ccols = _cols("cluster")
    if ccols and "agent_id" not in ccols:
        op.add_column("cluster", sa.Column("agent_id", sa.String(36), nullable=False,
                                           server_default=""))
        # rescope the uniqueness from (lever, cluster_key) to (agent_id, lever, cluster_key)
        with op.batch_alter_table("cluster") as b:
            try:
                b.drop_constraint("uq_cluster", type_="unique")
            except Exception:  # noqa: BLE001 — SQLite/older builds may name it differently
                pass
            b.create_unique_constraint("uq_cluster", ["agent_id", "lever", "cluster_key"])

    cccols = _cols("call_cluster")
    if cccols and "agent_id" not in cccols:
        op.add_column("call_cluster", sa.Column("agent_id", sa.String(36), nullable=False,
                                                server_default=""))


def downgrade() -> None:
    if "agent_id" in _cols("call_cluster"):
        op.drop_column("call_cluster", "agent_id")
    if "agent_id" in _cols("cluster"):
        with op.batch_alter_table("cluster") as b:
            try:
                b.drop_constraint("uq_cluster", type_="unique")
            except Exception:  # noqa: BLE001
                pass
            b.create_unique_constraint("uq_cluster", ["lever", "cluster_key"])
        op.drop_column("cluster", "agent_id")
