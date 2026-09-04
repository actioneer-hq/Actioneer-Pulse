"""Agents (the "project"/OTLP routing target) + their ingest tokens. List is RBAC-scoped;
create/modify and token management require admin. The plaintext token is shown once at mint.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.orgs import slugify
from voiceobs.api.schemas import AgentIn, AgentPatchIn, AudioConfigIn, IngestTokenIn, ScriptIn
from voiceobs.auth import current_membership, mint_ingest_token, require_role, visible_agent_ids
from voiceobs.auth.crypto import encrypt
from voiceobs.db.models import (
    Agent,
    AgentAudioConfig,
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


def _apply_audio_config(db: Session, agent_id: str, body: AudioConfigIn) -> AgentAudioConfig:
    cfg = db.scalar(select(AgentAudioConfig).where(AgentAudioConfig.agent_id == agent_id))
    if cfg is None:
        cfg = AgentAudioConfig(agent_id=agent_id)
        db.add(cfg)
    cfg.enabled = body.enabled
    cfg.s3_bucket = body.s3_bucket
    cfg.s3_prefix = body.s3_prefix
    cfg.s3_region = body.s3_region
    cfg.s3_endpoint_url = body.s3_endpoint_url
    cfg.access_key_id = body.access_key_id
    if body.secret_access_key is not None:  # write-only: omit to keep the stored secret
        cfg.secret_ciphertext = encrypt(body.secret_access_key)
    cfg.stt_base_url = body.stt_base_url
    cfg.stt_model = body.stt_model
    if body.stt_api_key is not None:  # write-only
        cfg.stt_key_ciphertext = encrypt(body.stt_api_key)
    cfg.updated_at = now()
    return cfg


def _audio_config_dict(cfg: AgentAudioConfig | None) -> dict:
    if cfg is None:
        return {"enabled": False, "has_secret": False}
    return {
        "enabled": cfg.enabled,
        "s3_bucket": cfg.s3_bucket,
        "s3_prefix": cfg.s3_prefix,
        "s3_region": cfg.s3_region,
        "s3_endpoint_url": cfg.s3_endpoint_url,
        "access_key_id": cfg.access_key_id,
        "has_secret": cfg.secret_ciphertext is not None,  # never echo the secret itself
        "stt_base_url": cfg.stt_base_url,
        "stt_model": cfg.stt_model,
        "has_stt_key": cfg.stt_key_ciphertext is not None,
    }


# --- agent script (versioned, hash-addressed, pinned per call) ----------------- #


def set_agent_script(db: Session, agent: Agent, text: str, user_id: str | None) -> AgentScript:
    """Set/replace the agent's script. Content dedupes into Prompt by sha256; a new AgentScript
    version is minted only when the text actually changes. Returns the active version."""
    sha = hashlib.sha256(text.encode()).hexdigest()
    prompt = db.scalar(select(Prompt).where(
        Prompt.tenant_id == agent.org_id, Prompt.template_sha256 == sha))
    if prompt is None:
        prompt = Prompt(tenant_id=agent.org_id, template_sha256=sha, text=text)
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
