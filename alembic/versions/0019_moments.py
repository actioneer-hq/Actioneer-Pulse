"""Clusters rewrite: moment + moment_cluster replace call_embedding / cluster / call_cluster.

The old clustering embedded per-call judge prose; the new one clusters located journey failures
(moments). Drops the old tables (and the agent views over them), creates the new ones, and rebuilds the
org's agent views. Runs per schema (see alembic/env.py). Idempotent.

Revision ID: 0019_moments
Revises: 0018_journey_stages
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019_moments"
down_revision = "0018_journey_stages"
branch_labels = None
depends_on = None

_OLD = ("call_cluster", "cluster", "call_embedding")
_OLD_VIEWS = ("call_clusters", "clusters", "call_embeddings")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _rebuild_views(bind, is_pg: bool) -> None:
    from sqlalchemy.orm import Session

    from voiceobs.db.agent_views import build_agent_views

    schema = bind.execute(sa.text("SELECT current_schema()")).scalar() if is_pg else "t_default"
    if not schema or not schema.startswith("t_"):
        return
    with Session(bind=bind) as db:
        build_agent_views(db, schema[2:])
        db.flush()


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if "call" not in _tables():
        return
    if not is_pg:
        for v in _OLD_VIEWS:
            op.execute(f"DROP VIEW IF EXISTS {v}")
    for t in _OLD:
        if t in _tables():
            op.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE' if is_pg else f"DROP TABLE IF EXISTS {t}")

    if "moment" not in _tables():
        from voiceobs.db.types import Embedding

        if is_pg:  # the pgvector `vector` type lives in public
            schema = bind.execute(sa.text("SELECT current_schema()")).scalar()
            op.execute(f'SET search_path TO "{schema}", public')
        op.create_table(
            "moment",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("call_id", sa.String(36), sa.ForeignKey("call.id"), nullable=False),
            sa.Column("agent_id", sa.String(36), nullable=False),
            sa.Column("prompt_id", sa.String(36), nullable=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("item", sa.Text(), nullable=False),
            sa.Column("cause", sa.String(16), nullable=False),
            sa.Column("turn", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("embedding", Embedding(), nullable=True),
            sa.Column("cluster_key", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("call_id", "kind", "item", "turn", name="uq_moment"),
        )
        op.create_index("ix_moment_group", "moment", ["agent_id", "prompt_id", "kind"])
        if is_pg:
            op.execute(f'SET search_path TO "{schema}"')
    if "moment_cluster" not in _tables():
        op.create_table(
            "moment_cluster",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("agent_id", sa.String(36), nullable=False),
            sa.Column("prompt_id", sa.String(36), nullable=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("item", sa.Text(), nullable=False),
            sa.Column("cause", sa.String(16), nullable=False),
            sa.Column("cluster_key", sa.Integer(), nullable=False),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("size", sa.Integer(), nullable=False),
            sa.Column("members_hash", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("agent_id", "prompt_id", "kind", "item", "cause", "cluster_key",
                                name="uq_moment_cluster"),
        )
    _rebuild_views(bind, is_pg)


def downgrade() -> None:
    for t in ("moment_cluster", "moment"):
        if t in _tables():
            op.drop_table(t)
