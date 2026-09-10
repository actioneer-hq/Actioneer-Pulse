"""Agents (the "project"/OTLP routing target) + their ingest tokens. List is RBAC-scoped;
create/modify and token management require admin. The plaintext token is shown once at mint.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.orgs import slugify
from voiceobs.api.schemas import (
    AgentIn,
    AgentPatchIn,
    AudioConfigIn,
    GuardrailsIn,
    IngestTokenIn,
    OtlpMappingIn,
    ScriptIn,
)
from voiceobs.auth import current_membership, mint_ingest_token, require_role, visible_agent_ids
from voiceobs.auth.crypto import decrypt, encrypt
from voiceobs.db.models import (
    Agent,
    AgentAudioConfig,
    AgentGuardrail,
    AgentOtlpMapping,
    AgentScript,
    IngestToken,
    Membership,
    Prompt,
)

router = APIRouter(prefix="/v1/agents")


def _unique_agent_slug(db: Session, org_id: str, base: str) -> str:
    slug = slugify(base)
    taken = {a.slug for a in db.scalars(select(Agent).where(Agent.org_id == org_id))}
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"


def _org_agent(db: Session, mem: Membership, agent_id: str) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.org_id == mem.org_id))
    if agent is None:
        raise HTTPException(404, "agent not found")
    ids = visible_agent_ids(db, mem)
    if ids is not None and agent.id not in ids:
        raise HTTPException(404, "agent not found")
    return agent


def _agent_dict(a: Agent) -> dict:
    return {"id": a.id, "name": a.name, "slug": a.slug, "org_id": a.org_id}


@router.get("")
def list_agents(
    mem: Membership = Depends(current_membership), db: Session = Depends(session_dep)
) -> dict:
    stmt = select(Agent).where(Agent.org_id == mem.org_id)
    ids = visible_agent_ids(db, mem)
    if ids is not None:
        stmt = stmt.where(Agent.id.in_(ids))
    return {"items": [_agent_dict(a) for a in db.scalars(stmt)]}


@router.post("")
def create_agent(
    body: AgentIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = Agent(org_id=mem.org_id, name=body.name,
                  slug=_unique_agent_slug(db, mem.org_id, body.slug or body.name))
    db.add(agent)
    db.flush()
    if body.audio is not None:
        _apply_audio_config(db, agent.id, body.audio)
    if body.script:
        set_agent_script(db, agent, body.script, mem.user_id)
    if body.guardrails:
        set_agent_guardrails(db, agent, body.guardrails, mem.user_id)
    return _agent_dict(agent)


@router.patch("/{agent_id}")
def rename_agent(
    agent_id: str, body: AgentPatchIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = _org_agent(db, mem, agent_id)
    agent.name = body.name
    return _agent_dict(agent)


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = _org_agent(db, mem, agent_id)
    db.delete(agent)
    return {"status": "ok"}


@router.get("/{agent_id}/ingest-tokens")
def list_tokens(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    _org_agent(db, mem, agent_id)
    rows = db.scalars(
        select(IngestToken).where(IngestToken.agent_id == agent_id)
    ).all()
    return {"items": [
        {"id": t.id, "prefix": t.token_prefix, "name": t.name,
         "revoked": t.revoked_at is not None, "last_used_at": t.last_used_at}
        for t in rows
    ]}


@router.post("/{agent_id}/ingest-tokens")
def create_token(
    agent_id: str, body: IngestTokenIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = _org_agent(db, mem, agent_id)
    plaintext, row = mint_ingest_token(db, agent.org_id, agent.id, body.name)
    db.flush()
    return {"id": row.id, "token": plaintext, "prefix": row.token_prefix}  # token shown once


@router.post("/{agent_id}/ingest-tokens/{tid}/rotate")
def rotate_token(
    agent_id: str, tid: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = _org_agent(db, mem, agent_id)
    old = db.scalar(select(IngestToken).where(IngestToken.id == tid, IngestToken.agent_id == agent_id))
    if old is None:
        raise HTTPException(404, "token not found")
    old.revoked_at = now()
    plaintext, row = mint_ingest_token(db, agent.org_id, agent.id, old.name)
    db.flush()
    return {"id": row.id, "token": plaintext, "prefix": row.token_prefix}


@router.delete("/{agent_id}/ingest-tokens/{tid}")
def revoke_token(
    agent_id: str, tid: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    _org_agent(db, mem, agent_id)
    tok = db.scalar(select(IngestToken).where(IngestToken.id == tid, IngestToken.agent_id == agent_id))
    if tok is None:
        raise HTTPException(404, "token not found")
    tok.revoked_at = now()
    return {"status": "ok"}


# --- audio analysis config (per-agent S3, pull path) --------------------------- #


def _secret_names(spec: list | None) -> set[str]:
    return {f["name"] for f in (spec or []) if f.get("secret")}


def _apply_audio_config(db: Session, agent_id: str, body: AudioConfigIn) -> AgentAudioConfig:
    cfg = db.scalar(select(AgentAudioConfig).where(AgentAudioConfig.agent_id == agent_id))
    if cfg is None:
        cfg = AgentAudioConfig(agent_id=agent_id)
        db.add(cfg)
    cfg.enabled = body.enabled
    if body.provider is not None:
        cfg.provider = body.provider
    if body.descriptor is not None:
        cfg.descriptor = body.descriptor
    if body.cred_spec is not None:
        cfg.cred_spec = body.cred_spec
    if body.credentials is not None:
        secret_names = _secret_names(cfg.cred_spec)
        # non-secret values are stored plaintext + echoed; secret values are merged over the stored
        # set (write-only: omit a secret field to keep its stored value) and encrypted.
        cfg.cred_public = {k: v for k, v in body.credentials.items() if k not in secret_names}
        existing = json.loads(decrypt(cfg.cred_secret_ciphertext) or "{}")
        provided = {k: v for k, v in body.credentials.items() if k in secret_names and v}
        merged = {**existing, **provided}
        cfg.cred_secret_ciphertext = encrypt(json.dumps(merged)) if merged else None
    cfg.stt_base_url = body.stt_base_url
    cfg.stt_model = body.stt_model
    if body.stt_api_key is not None:  # write-only
        cfg.stt_key_ciphertext = encrypt(body.stt_api_key)
    cfg.diarize_base_url = body.diarize_base_url
    cfg.diarize_model = body.diarize_model
    if body.diarize_api_key is not None:  # write-only
        cfg.diarize_key_ciphertext = encrypt(body.diarize_api_key)
    cfg.updated_at = now()
    return cfg


def _audio_config_dict(cfg: AgentAudioConfig | None) -> dict:
    if cfg is None:
        return {"enabled": False, "provider": None, "descriptor": None, "cred_spec": None,
                "cred_public": {}, "has_secret": {}}
    stored_secrets = set(json.loads(decrypt(cfg.cred_secret_ciphertext) or "{}"))
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "descriptor": cfg.descriptor,
        "cred_spec": cfg.cred_spec,
        "cred_public": cfg.cred_public or {},
        # per-secret-field presence so the UI can show "stored" — never the secret values.
        "has_secret": {n: (n in stored_secrets) for n in _secret_names(cfg.cred_spec)},
        "stt_base_url": cfg.stt_base_url,
        "stt_model": cfg.stt_model,
        "has_stt_key": cfg.stt_key_ciphertext is not None,
        "diarize_base_url": cfg.diarize_base_url,
        "diarize_model": cfg.diarize_model,
        "has_diarize_key": cfg.diarize_key_ciphertext is not None,
    }


# --- agent script (versioned, hash-addressed, pinned per call) ----------------- #


def set_agent_script(db: Session, agent: Agent, text: str, user_id: str | None) -> AgentScript:
    """Set/replace the agent's script. Content dedupes into Prompt by sha256; a new AgentScript
    version is minted only when the text actually changes. Returns the active version."""
    sha = hashlib.sha256(text.encode()).hexdigest()
    prompt = db.scalar(select(Prompt).where(Prompt.template_sha256 == sha))
    if prompt is None:
        prompt = Prompt(template_sha256=sha, text=text)
        db.add(prompt)
        db.flush()

    active = db.scalar(select(AgentScript).where(
        AgentScript.agent_id == agent.id, AgentScript.active.is_(True)))
    if active is not None and active.prompt_id == prompt.id:
        return active  # identical script — no new version

    if active is not None:
        active.active = False
    last = db.scalar(select(AgentScript.version).where(AgentScript.agent_id == agent.id)
                     .order_by(AgentScript.version.desc()))
    row = AgentScript(agent_id=agent.id, prompt_id=prompt.id, version=(last or 0) + 1,
                      created_by=user_id, active=True)
    db.add(row)
    db.flush()
    return row


def _script_dict(db: Session, s: AgentScript | None, *, with_text: bool = False) -> dict | None:
    if s is None:
        return None
    p = db.get(Prompt, s.prompt_id)
    out = {"version": s.version, "sha256": p.template_sha256 if p else None,
           "created_by": s.created_by, "created_at": s.created_at}
    if with_text:
        out["text"] = p.text if p else None
    return out


@router.put("/{agent_id}/script")
def set_script(
    agent_id: str, body: ScriptIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = _org_agent(db, mem, agent_id)
    row = set_agent_script(db, agent, body.text, mem.user_id)
    db.flush()
    return _script_dict(db, row) or {}


@router.get("/{agent_id}/script")
def get_script(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> dict:
    _org_agent(db, mem, agent_id)
    active = db.scalar(select(AgentScript).where(
        AgentScript.agent_id == agent_id, AgentScript.active.is_(True)))
    return _script_dict(db, active, with_text=True) or {"version": None, "text": None}


@router.get("/{agent_id}/scripts")
def list_scripts(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> dict:
    _org_agent(db, mem, agent_id)
    rows = db.scalars(select(AgentScript).where(AgentScript.agent_id == agent_id)
                      .order_by(AgentScript.version.desc())).all()
    return {"items": [{**_script_dict(db, r), "active": r.active} for r in rows]}


# --- agent guardrails (versioned, hash-addressed; mirrors scripts) ------------- #


def set_agent_guardrails(db: Session, agent: Agent, text: str, user_id: str | None) -> AgentGuardrail:
    """Set/replace the agent's guardrails. Content dedupes into Prompt by sha256; a new version is
    minted only when the text changes. Returns the active version."""
    sha = hashlib.sha256(text.encode()).hexdigest()
    prompt = db.scalar(select(Prompt).where(Prompt.template_sha256 == sha))
    if prompt is None:
        prompt = Prompt(template_sha256=sha, text=text)
        db.add(prompt)
        db.flush()

    active = db.scalar(select(AgentGuardrail).where(
        AgentGuardrail.agent_id == agent.id, AgentGuardrail.active.is_(True)))
    if active is not None and active.prompt_id == prompt.id:
        return active  # identical guardrails — no new version

    if active is not None:
        active.active = False
    last = db.scalar(select(AgentGuardrail.version).where(AgentGuardrail.agent_id == agent.id)
                     .order_by(AgentGuardrail.version.desc()))
    row = AgentGuardrail(agent_id=agent.id, prompt_id=prompt.id, version=(last or 0) + 1,
                         created_by=user_id, active=True)
    db.add(row)
    db.flush()
    return row


def _guardrails_dict(db: Session, g: AgentGuardrail | None, *, with_text: bool = False) -> dict | None:
    if g is None:
        return None
    p = db.get(Prompt, g.prompt_id)
    out = {"version": g.version, "sha256": p.template_sha256 if p else None,
           "created_by": g.created_by, "created_at": g.created_at}
    if with_text:
        out["text"] = p.text if p else None
    return out


@router.put("/{agent_id}/guardrails")
def set_guardrails(
    agent_id: str, body: GuardrailsIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    agent = _org_agent(db, mem, agent_id)
    row = set_agent_guardrails(db, agent, body.text, mem.user_id)
    db.flush()
    return _guardrails_dict(db, row) or {}


@router.get("/{agent_id}/guardrails")
def get_guardrails(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> dict:
    _org_agent(db, mem, agent_id)
    active = db.scalar(select(AgentGuardrail).where(
        AgentGuardrail.agent_id == agent_id, AgentGuardrail.active.is_(True)))
    return _guardrails_dict(db, active, with_text=True) or {"version": None, "text": None}


@router.get("/{agent_id}/guardrails/versions")
def list_guardrails(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(current_membership),
) -> dict:
    _org_agent(db, mem, agent_id)
    rows = db.scalars(select(AgentGuardrail).where(AgentGuardrail.agent_id == agent_id)
                      .order_by(AgentGuardrail.version.desc())).all()
    return {"items": [{**_guardrails_dict(db, r), "active": r.active} for r in rows]}


@router.get("/{agent_id}/audio-config")
def get_audio_config(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    _org_agent(db, mem, agent_id)
    cfg = db.scalar(select(AgentAudioConfig).where(AgentAudioConfig.agent_id == agent_id))
    return _audio_config_dict(cfg)


@router.put("/{agent_id}/audio-config")
def set_audio_config(
    agent_id: str, body: AudioConfigIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    _org_agent(db, mem, agent_id)
    cfg = _apply_audio_config(db, agent_id, body)
    db.flush()
    return _audio_config_dict(cfg)


@router.get("/{agent_id}/otlp-mapping")
def get_otlp_mapping(
    agent_id: str,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    _org_agent(db, mem, agent_id)
    row = db.scalar(select(AgentOtlpMapping).where(AgentOtlpMapping.agent_id == agent_id))
    if row is None:
        raise HTTPException(404, "no otlp mapping configured")
    return {"expression": row.expression, "version": row.version, "updated_at": row.updated_at}


@router.put("/{agent_id}/otlp-mapping")
def set_otlp_mapping(
    agent_id: str, body: OtlpMappingIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    """Store this agent's JSONata OTLP mapping (upsert, bumps version). The expression is parse-checked
    here; the wizard is responsible for validating that its OUTPUT is a correct Trace."""
    _org_agent(db, mem, agent_id)
    return apply_otlp_mapping(db, agent_id, body.expression)


def apply_otlp_mapping(db: Session, agent_id: str, expression: str) -> dict:
    """Parse-check + upsert an agent's JSONata OTLP mapping (schema assumed pinned, agent authorized).
    Shared by the admin endpoint and the token-authenticated /v1/ingest sibling."""
    try:
        import jsonata

        jsonata.Jsonata(expression)
    except ImportError:
        pass  # engine only present on the analysis service; skip the parse check where unavailable
    except Exception as e:
        raise HTTPException(422, f"invalid jsonata expression: {e}") from e

    row = db.scalar(select(AgentOtlpMapping).where(AgentOtlpMapping.agent_id == agent_id))
    if row is None:
        row = AgentOtlpMapping(agent_id=agent_id, expression=expression, version=1)
        db.add(row)
    else:
        row.expression = expression
        row.version += 1
        row.updated_at = now()
    db.flush()
    return {"expression": row.expression, "version": row.version, "updated_at": row.updated_at}
