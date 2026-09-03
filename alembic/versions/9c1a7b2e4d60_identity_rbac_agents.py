"""identity: organization / app_user / membership / agent / agent_access / ingest_token
+ call.agent_id, with backfill of a default org + agent per existing tenant.

Revision ID: 9c1a7b2e4d60
Revises: 8b1d5f2a9c44
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c1a7b2e4d60"
down_revision: str | Sequence[str] | None = "8b1d5f2a9c44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_organization_slug"),
    )
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("name", sa.String(128)),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )
    op.create_table(
        "membership",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership"),
    )
    op.create_index("ix_membership_user", "membership", ["user_id"])
    op.create_index("ix_membership_org", "membership", ["org_id"])
    op.create_table(
        "agent",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "slug", name="uq_agent_slug"),
    )
    op.create_index("ix_agent_org", "agent", ["org_id"])
    op.create_table(
        "agent_access",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("membership_id", sa.String(36), sa.ForeignKey("membership.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("membership_id", "agent_id", name="uq_agent_access"),
    )
    op.create_table(
        "ingest_token",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(128)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingest_token_prefix", "ingest_token", ["token_prefix"])

    # loose ref (no DB-level FK), like tenant_id -> organization; SQLite can't ALTER-add a
    # constrained column anyway.
    op.add_column("call", sa.Column("agent_id", sa.String(36)))
    op.create_index("ix_call_agent_id", "call", ["agent_id"])

    # ── backfill (SQLite + Postgres safe; CURRENT_TIMESTAMP + || concat work on both) ──
    # 1. seed the default org, 2. an org per existing distinct tenant, 3. a default agent
    # per org, 4. point every pre-existing call at its org's default agent. Idempotent via
    # NOT EXISTS guards. Deterministic agent id = "<org_id>-default".
    op.execute(
        "INSERT INTO organization (id, name, slug, created_at) "
        "SELECT 'default', 'Default', 'default', CURRENT_TIMESTAMP "
        "WHERE NOT EXISTS (SELECT 1 FROM organization WHERE id = 'default')"
    )
    op.execute(
        "INSERT INTO organization (id, name, slug, created_at) "
        "SELECT DISTINCT c.tenant_id, c.tenant_id, c.tenant_id, CURRENT_TIMESTAMP "
        "FROM call c "
        "WHERE NOT EXISTS (SELECT 1 FROM organization o WHERE o.id = c.tenant_id)"
    )
    op.execute(
        "INSERT INTO agent (id, org_id, name, slug, created_at) "
        "SELECT o.id || '-default', o.id, 'Default', 'default', CURRENT_TIMESTAMP "
        "FROM organization o "
        "WHERE NOT EXISTS (SELECT 1 FROM agent a WHERE a.org_id = o.id AND a.slug = 'default')"
    )
    op.execute("UPDATE call SET agent_id = tenant_id || '-default' WHERE agent_id IS NULL")


def downgrade() -> None:
    op.drop_index("ix_call_agent_id", table_name="call")
    op.drop_column("call", "agent_id")
    op.drop_index("ix_ingest_token_prefix", table_name="ingest_token")
    op.drop_table("ingest_token")
    op.drop_table("agent_access")
    op.drop_index("ix_agent_org", table_name="agent")
    op.drop_table("agent")
    op.drop_index("ix_membership_org", table_name="membership")
    op.drop_index("ix_membership_user", table_name="membership")
    op.drop_table("membership")
    op.drop_table("app_user")
    op.drop_table("organization")
