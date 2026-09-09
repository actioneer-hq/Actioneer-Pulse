"""Resolve a per-agent OTLP translation (a JSONata expression) from AgentOtlpMapping.

Kept out of `frameworks/` so adapters stay DB-free — the analysis worker resolves the mapping here
(mirroring how it pulls `resolve_creds` from `storage/config.py`) and hands the plain expression string
to `frameworks.jsonata.JSONataAdapter`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.db.models import AgentOtlpMapping


def resolve_mapping(db: Session, agent_id: str | None) -> tuple[str, int] | None:
    """The (expression, version) for an agent, or None (no mapping → built-in adapters run)."""
    if not agent_id:
        return None
    row = db.scalar(select(AgentOtlpMapping).where(AgentOtlpMapping.agent_id == agent_id))
    if row is None:
        return None
    return row.expression, row.version
