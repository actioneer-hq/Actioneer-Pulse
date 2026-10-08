"""Analysis notifications: recent uploads / backfills with the progress of each decoupled stage (decision
model, LLM, training data, clustering, script improvement) and the events of stages that finished.

GET /v1/notifications   recent analyses of the projects the caller can see (newest first)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.auth import current_membership, visible_agent_ids
from voiceobs.db.models import Agent, BackfillJob, Membership
from voiceobs.worker.pipeline import progress

router = APIRouter(prefix="/v1/notifications")
_LIMIT = 8


@router.get("")
def notifications(db: Session = Depends(session_dep), mem: Membership = Depends(current_membership)) -> dict:
    ids = visible_agent_ids(db, mem)
    stmt = select(BackfillJob).order_by(BackfillJob.created_at.desc()).limit(40)
    items = []
    for job in db.scalars(stmt):
        pipe = (job.options or {}).get("pipeline")
        if not pipe or (ids is not None and job.agent_id not in ids):
            continue
        agent = db.get(Agent, job.agent_id) if job.agent_id else None
        if agent is None:
            continue  # its project was deleted
        items.append({"id": job.id, "agent_id": job.agent_id, "agent": agent.name if agent else None,
                      "created_at": job.created_at, "calls": len(pipe.get("calls") or []),
                      "complete": bool(pipe.get("complete")), "stages": progress(db, job),
                      "events": pipe.get("events") or []})
        if len(items) >= _LIMIT:
            break
    return {"items": items}
