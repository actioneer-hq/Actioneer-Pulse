"""Script improvement (RSI) API for a project's active script version.

POST /v1/agents/{id}/script-rsi                      start a run (the backfill worker executes it)
GET  /v1/agents/{id}/script-rsi                      recent runs with their results
POST /v1/agents/{id}/script-rsi/{run_id}/approve     {variant: additions|A|B} -> the next script version
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.agents import _org_agent, set_agent_script
from voiceobs.api.deps import now, session_dep
from voiceobs.auth import current_membership, require_role
from voiceobs.db.models import AgentJourney, AgentScript, Membership, ScriptProposal
from voiceobs.worker.journey import ensure_pending, ready_journey

router = APIRouter(prefix="/v1/agents")


class ApproveIn(BaseModel):
    variant: str


def _dict(r: ScriptProposal) -> dict:
    return {"id": r.id, "status": r.status, "prompt_id": r.prompt_id, "result": r.result, "error": r.error,
            "approved_variant": r.approved_variant, "created_at": r.created_at, "updated_at": r.updated_at}


def _active(db: Session, agent_id: str) -> AgentScript | None:
    return db.scalar(select(AgentScript).where(AgentScript.agent_id == agent_id, AgentScript.active.is_(True)))


@router.post("/{agent_id}/script-rsi")
def start(agent_id: str, db: Session = Depends(session_dep),
          mem: Membership = Depends(require_role("owner", "admin"))) -> dict:
    agent = _org_agent(db, mem, agent_id)
    script = _active(db, agent.id)
    if script is None or not ready_journey(db, script.prompt_id):
        raise HTTPException(422, "the project needs a script with a ready script journey")
    row = ScriptProposal(agent_id=agent.id, prompt_id=script.prompt_id, status="pending", created_by=mem.user_id)
    db.add(row)
    db.flush()
    return _dict(row)


@router.get("/{agent_id}/script-rsi")
def runs(agent_id: str, db: Session = Depends(session_dep),
         mem: Membership = Depends(current_membership)) -> dict:
    agent = _org_agent(db, mem, agent_id)
    rows = db.scalars(select(ScriptProposal).where(ScriptProposal.agent_id == agent.id)
                      .order_by(ScriptProposal.created_at.desc()).limit(5)).all()
    return {"items": [_dict(r) for r in rows]}


@router.post("/{agent_id}/script-rsi/{run_id}/approve")
def approve(agent_id: str, run_id: str, body: ApproveIn, db: Session = Depends(session_dep),
            mem: Membership = Depends(require_role("owner", "admin"))) -> dict:
    """Mint the next script version from a variant; its journey is the variant's (no re-extraction)."""
    agent = _org_agent(db, mem, agent_id)
    row = db.get(ScriptProposal, run_id)
    if row is None or row.agent_id != agent.id or row.status != "ready":
        raise HTTPException(404, "no ready improvement run with that id")
    variant = (row.result or {}).get("variants", {}).get(body.variant)
    if variant is None:
        raise HTTPException(422, f"unknown variant {body.variant!r}")
    script = set_agent_script(db, agent, variant["text"], mem.user_id)
    journey = ensure_pending(db, script.prompt_id)
    journey.journey, journey.status, journey.edited = variant["journey"], "ready", True
    journey.model, journey.error, journey.updated_at = "script_rsi", None, now()
    row.approved_variant = body.variant
    db.flush()
    return {"version": script.version, "prompt_id": script.prompt_id, "chars": variant["chars"],
            "journey": db.scalar(select(AgentJourney.status).where(AgentJourney.prompt_id == script.prompt_id))}
