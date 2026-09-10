"""Token-authenticated self-registration: an agent's own ingest token configures that agent.

The onboarding wizard has only the agent's ingest token (endpoint + token DX) — not an owner session —
so it can't reach the admin `/v1/agents/{id}/...` endpoints. These siblings authenticate with the
ingest token itself (which already identifies the agent), so the wizard can register the generated
JSONata OTLP mapping and the storage config. Same underlying upserts as the admin endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from voiceobs.api.agents import _apply_audio_config, apply_otlp_mapping
from voiceobs.api.deps import session_dep
from voiceobs.api.schemas import AudioConfigIn, OtlpMappingIn
from voiceobs.auth import resolve_ingest_token
from voiceobs.db.session import use_org_schema

router = APIRouter(prefix="/v1/ingest")

_ORG_HEADER = "X-Voiceobs-Org"


def require_ingest_agent(
    db: Session = Depends(session_dep),
    authorization: str | None = Header(None),
    x_token: str | None = Header(None, alias="X-Voiceobs-Token"),
    x_org: str = Header("default", alias=_ORG_HEADER),
) -> tuple[str, Session]:
    """Resolve the agent from its ingest token (Bearer or X-Voiceobs-Token), pinning the org schema
    first (default 'default'). Returns (agent_id, db). 401 on a missing/invalid/revoked token."""
    use_org_schema(db, x_org)  # pin the schema before any DB lookup (incl. the token)
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or x_token
    resolved = resolve_ingest_token(db, token) if token else None
    if resolved is None:
        raise HTTPException(401, "valid ingest token required")
    _org_id, agent_id = resolved
    if agent_id is None:  # a token not bound to a specific agent can't self-configure
        raise HTTPException(403, "token is not bound to an agent")
    return agent_id, db


@router.put("/otlp-mapping")
def put_otlp_mapping(
    body: OtlpMappingIn, ident: tuple[str, Session] = Depends(require_ingest_agent)
) -> dict:
    agent_id, db = ident
    return apply_otlp_mapping(db, agent_id, body.expression)


@router.put("/storage-config")
def put_storage_config(
    body: AudioConfigIn, ident: tuple[str, Session] = Depends(require_ingest_agent)
) -> dict:
    agent_id, db = ident
    cfg = _apply_audio_config(db, agent_id, body)
    db.flush()
    return {"agent_id": agent_id, "enabled": cfg.enabled, "provider": cfg.provider}
