"""Token-authenticated self-registration: an agent's own ingest token configures that agent.

The onboarding wizard has only the agent's ingest token (endpoint + token DX) — not an owner session —
so it can't reach the admin `/v1/agents/{id}/...` endpoints. These siblings authenticate with the
ingest token itself (which already identifies the agent), so the wizard can register the generated
JSONata OTLP mapping and the storage config. Same underlying upserts as the admin endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs import telemetry
from voiceobs.api.agents import _apply_audio_config, apply_otlp_mapping
from voiceobs.api.deps import session_dep
from voiceobs.api.schemas import AgentMetaIn, AudioConfigIn, OtlpMappingIn
from voiceobs.auth import resolve_ingest_token
from voiceobs.db.models import Agent
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


@router.put("/integration-manifest")
def put_integration_manifest(
    body: dict, ident: tuple[str, Session] = Depends(require_ingest_agent)
) -> dict:
    """Register the wizard's integration manifest (schema pulse.integration) for this agent.
    Stored as data; executed by the manifest runtime during a `source=manifest` backfill.
    Upsert — a re-register replaces the manifest and bumps `version` for provenance."""
    agent_id, db = ident
    if body.get("schema") != "pulse.integration":
        raise HTTPException(422, "manifest schema must be pulse.integration")
    if not isinstance(body.get("mappers"), dict) or not isinstance(body.get("artifacts"), list):
        raise HTTPException(422, "manifest requires mappers and artifacts")
    from voiceobs.db.models import AgentIntegrationManifest

    row = db.scalar(
        select(AgentIntegrationManifest).where(AgentIntegrationManifest.agent_id == agent_id)
    )
    if row is None:
        row = AgentIntegrationManifest(agent_id=agent_id, manifest=body, version=1)
        db.add(row)
    else:
        row.manifest = body
        row.version += 1
    db.flush()
    return {"agent_id": agent_id, "version": row.version,
            "mappers": len(body["mappers"]), "artifacts": len(body["artifacts"])}


@router.get("/integration-manifest")
def get_integration_manifest(ident: tuple[str, Session] = Depends(require_ingest_agent)) -> dict:
    agent_id, db = ident
    from voiceobs.db.models import AgentIntegrationManifest

    row = db.scalar(
        select(AgentIntegrationManifest).where(AgentIntegrationManifest.agent_id == agent_id)
    )
    if row is None:
        raise HTTPException(404, "no integration manifest registered")
    return {"agent_id": agent_id, "version": row.version, "manifest": row.manifest}


@router.put("/agent-meta")
def put_agent_meta(
    body: AgentMetaIn, ident: tuple[str, Session] = Depends(require_ingest_agent)
) -> dict:
    """Set the wizard-inferred market use-case on the agent, and emit the anonymized `agent.configured`
    telemetry (framework/language are telemetry-only, not stored)."""
    agent_id, db = ident
    agent = db.scalar(select(Agent).where(Agent.id == agent_id))
    if agent is None:
        raise HTTPException(404, "agent not found")
    if body.use_case is not None:
        agent.use_case = body.use_case[:160]
    telemetry.agent_configured(
        use_case=agent.use_case, framework=body.framework, language=body.language
    )
    return {"agent_id": agent_id, "use_case": agent.use_case}
