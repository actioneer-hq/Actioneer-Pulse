"""Org (schema) provisioning for schema-per-tenant.

Creating an org means creating its Postgres schema and building the entire table set inside it, then
seeding its `organization` row. On SQLite (dev/tests) there is a single flat schema, so provisioning
only ensures the tables exist and the org row is present. `provision_org` is idempotent."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from voiceobs.db.agent_views import build_agent_views
from voiceobs.db.base import Base
from voiceobs.db.models import Organization
from voiceobs.db.session import DEFAULT_ORG, org_schema, use_org_schema


def provision_org(db: Session, slug: str, name: str | None = None) -> Organization:
    """Ensure the org's schema exists, is fully built, and holds its organization row. Returns the
    Organization (created or existing). The session is left pinned to the org's schema."""
    slug = (slug or DEFAULT_ORG).lower()
    bind = db.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        db.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{org_schema(slug)}"'))
        # Include `public` in the search_path for the DDL: the pgvector `vector` type is installed
        # in public, so a VECTOR column (call_embedding.embedding) only resolves if public is on the
        # path. Without this, creating a fresh tenant schema fails with "type vector does not exist".
        db.execute(text(f'SET search_path TO "{org_schema(slug)}", public'))
        Base.metadata.create_all(db.connection())
    use_org_schema(db, slug)  # pin to the org schema ALONE for DML (keeps tenant isolation on return)

    # Build the read-only agent view menu (ag_<slug> + grants on PG; flat views on SQLite).
    build_agent_views(db, slug)

    org = db.scalar(select(Organization))  # one org per schema
    if is_pg and org is not None and org.slug != slug:
        # a DIFFERENT org already lives in this PG schema — the requested slug sanitized onto an
        # existing tenant's schema (e.g. "a_b" vs "a-b" both → t_a_b). Refuse to co-tenant.
        # (On SQLite every org shares the one flat schema by design, so this never applies.)
        raise ValueError(
            f"slug {slug!r} collides with existing org {org.slug!r} (same schema {org_schema(slug)})"
        )
    if org is None:
        display = name or slug.capitalize()
        # keep the well-known "default" id stable; other orgs get a generated uuid pk.
        org = (Organization(id=DEFAULT_ORG, name=display, slug=slug) if slug == DEFAULT_ORG
               else Organization(name=display, slug=slug))
        db.add(org)
        db.flush()
    return org
