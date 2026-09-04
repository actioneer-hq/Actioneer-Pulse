"""Judge API — BYO model config (per org) + per-call judgment. Org comes from the session;
config writes require admin; calls are resolved through the RBAC-scoped dependency."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import now, session_dep
from voiceobs.api.schemas import JudgeConfigIn
from voiceobs.auth import current_membership, get_scoped_call, require_role
from voiceobs.db.models import Call, JudgeConfig, Judgment, Membership
from voiceobs.judge import judge_call

router = APIRouter(prefix="/v1")

_LLM_FIELDS = (
    "sentiment", "objective_achieved", "answered_by", "primary_language",
    "secondary_languages", "script_adherence", "escalation_requested",
    "callback_requested", "callback_time", "summary",
)


@router.post("/judge/config")
def set_judge_config(
    body: JudgeConfigIn,
    db: Session = Depends(session_dep),
    mem: Membership = Depends(require_role("owner", "admin")),
) -> dict:
    cfg = db.scalar(select(JudgeConfig).where(JudgeConfig.tenant_id == mem.org_id))
    if cfg is None:
        cfg = JudgeConfig(tenant_id=mem.org_id)
        db.add(cfg)
    cfg.base_url, cfg.model, cfg.params, cfg.enabled = (
        body.base_url, body.model, body.params, body.enabled
    )
    if body.api_key is not None:  # write-only; omit to keep the existing key
        cfg.api_key = body.api_key
    cfg.updated_at = now()
    return {"status": "ok"}


@router.get("/judge/config")
def get_judge_config(
    db: Session = Depends(session_dep), mem: Membership = Depends(current_membership)
) -> dict:
    cfg = db.scalar(select(JudgeConfig).where(JudgeConfig.tenant_id == mem.org_id))
    if cfg is None:
        raise HTTPException(404, "no judge config for org")
    return {
        "base_url": cfg.base_url, "model": cfg.model, "params": cfg.params,
        "enabled": cfg.enabled, "has_key": bool(cfg.api_key),  # never echo the key
    }


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
