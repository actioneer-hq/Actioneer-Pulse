"""Agents (the "project"/OTLP routing target) + their ingest tokens. List is RBAC-scoped;
create/modify and token management require admin. The plaintext token is shown once at mint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.orgs import slugify
from voiceobs.api.schemas import AgentIn, AgentPatchIn, IngestTokenIn
from voiceobs.auth import current_membership, mint_ingest_token, require_role, visible_agent_ids
from voiceobs.db.models import Agent, IngestToken, Membership

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
