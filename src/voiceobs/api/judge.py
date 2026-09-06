"""Judge API — per-call judgment. The model config lives in config.py + env, not the DB;
calls are resolved through the RBAC-scoped dependency."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.auth import get_scoped_call
from voiceobs.db.models import Call, Judgment
from voiceobs.judge import judge_call

router = APIRouter(prefix="/v1")

_LLM_FIELDS = (
    "sentiment", "objective_achieved", "answered_by", "primary_language",
    "secondary_languages", "script_adherence", "escalation_requested",
    "callback_requested", "callback_time", "summary",
)


@router.post("/calls/{call_id}/judge")
def run_judge(
    call: Call = Depends(get_scoped_call), db: Session = Depends(session_dep)
) -> dict:
    return _judgment_dict(judge_call(db, call))


@router.get("/calls/{call_id}/judgment")
def get_judgment(
    call: Call = Depends(get_scoped_call), db: Session = Depends(session_dep)
) -> dict:
    j = db.scalar(select(Judgment).where(Judgment.call_id == call.id))
    if j is None:
        raise HTTPException(404, "call not judged yet")
    return _judgment_dict(j)


def _judgment_dict(j: Judgment) -> dict:
    return {"disposition": j.disposition, "status": j.status, "model": j.model,
            "error": j.error, **{f: getattr(j, f) for f in _LLM_FIELDS}}
