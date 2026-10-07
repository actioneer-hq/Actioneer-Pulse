"""Judge one call: disposition (always), then up to two SEQUENTIAL LLM stages on connected calls.

Stage 1 — the post-call judge (JudgeOutput) gives the neutral quality read. Stage 2 —
failure-analysis (FailureAnalysis) root-causes the call, but runs ONLY when the judge's own
signals flag a shortfall (objective not fully achieved, or a guardrail broken). Deciding failure
from the judge (not from the analyst itself) removes the old bias of a "root-cause analyst" that
both declared and diagnosed failure, and avoids the second LLM call on clean calls. Own
transaction; neither model failure raises."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import resolve_llm
from voiceobs.db.models import Agent, AgentGuardrail, Call, CallParams, Judgment, Prompt
from voiceobs.judge.client import call_model
from voiceobs.judge.disposition import is_connected, programmatic_disposition
from voiceobs.judge.failure import analyze_failure
from voiceobs.judge.prompt import build_failure_messages, build_messages
from voiceobs.llm import LLMRole
from voiceobs.transcript import resolve

log = logging.getLogger(__name__)

# The post-call judge's output columns.
_JUDGE_FIELDS = (
    "sentiment", "objective_achieved", "answered_by", "primary_language",
    "secondary_languages", "script_adherence", "escalation_requested",
    "callback_requested", "callback_time", "guardrail_violation",
    "guardrail_violation_points", "summary",
)
# The failure-analysis LLM's output columns (populated by a separate model).
_FAILURE_FIELDS = (
    "is_failure", "root_cause", "model_fault", "model_fault_detail",
    "hallucination", "hallucination_detail", "suggested_fix", "llm_corrections",
)


def judge_call(db: Session, call: Call) -> Judgment:
    transcript = resolve(db, call)
    disposition = programmatic_disposition(call, transcript)
    j = _row(db, call)
    j.disposition = disposition

    if not is_connected(disposition):
        _clear(j, _JUDGE_FIELDS + _FAILURE_FIELDS)
        j.status, j.model = "skipped", None
        return j

    # Params gate: an agent with a parameterized prompt (params_required) must have this call's
    # per-call values before we judge — else the judge compares spoken values against the template's
    # example defaults and mislabels correct behaviour. Skip with a reason the UI can surface; a
    # later CSV upload re-enqueues the judge (see api/call_params.py).
    params = resolve_params(db, call)
    if _params_required(db, call) and params is None:
        _clear(j, _JUDGE_FIELDS + _FAILURE_FIELDS)
        j.status, j.model, j.error = "skipped", None, "no_params"
        return j

    script, guardrails = _script(db, call), _guardrails(db, call)
    ctx = (script, guardrails, transcript, call.external_call_id, params)

    # Sequential, two stages:
    #  1) the post-call judge produces the neutral quality read.
    #  2) failure analysis (root cause) runs ONLY when the judge's own signals say the call fell
    #     short — objective not fully achieved, or a guardrail broken. This replaces the old
    #     parallel design where a "root-cause analyst" both decided failure AND diagnosed it (biased
    #     toward finding failure), and it skips the second LLM call entirely on clean calls.
    judge_res = _judge(ctx)
    _apply_judge(j, judge_res)

    if _judge_flags_failure(judge_res):
        failure_res = _failure(ctx)
        if failure_res is not None:
            failure_res["is_failure"] = True  # the judge decided it failed; keep the RCA fields
        _apply_failure(j, failure_res if failure_res is not None else _FAILURE_DEFAULT)
    else:
        _apply_failure(j, _FAILURE_DEFAULT)  # not a failure → empty RCA block
    return j


# A connected call is a failure (→ run root-cause analysis) when the judge's neutral signals say so.
_FAILED_OBJECTIVES = {"not_achieved", "partial"}


def _judge_flags_failure(res: dict) -> bool:
    fields = res.get("fields") or {}
    if not fields:  # judge errored/skipped — no signal, so don't run RCA blindly
        return False
    obj = fields.get("objective_achieved")
    obj = obj.value if hasattr(obj, "value") else obj
    return bool(fields.get("guardrail_violation")) or obj in _FAILED_OBJECTIVES


# Default RCA block for calls the judge did NOT flag as failures (no second LLM call).
_FAILURE_DEFAULT = {
    "is_failure": False, "root_cause": None, "model_fault": "none", "model_fault_detail": None,
    "hallucination": False, "hallucination_detail": None, "suggested_fix": None,
    "llm_corrections": [],
}


def _judge(ctx) -> dict:
    """Run the post-call judge (stage 1). Returns plain results; never touches the DB."""
    script, guardrails, transcript, call_id, params = ctx
    resolved = resolve_llm(LLMRole.POST_CALL_ANALYSIS)
    if resolved is None:  # role not configured (no API key)
        return {"status": "skipped", "model": None, "fields": None, "error": None}
    try:
        out = call_model(resolved, build_messages(
            script, transcript, guardrails=guardrails, prompt=resolved.prompt, params=params))
        return {"status": "ok", "model": resolved.model,
                "fields": {f: getattr(out, f) for f in _JUDGE_FIELDS}, "error": None}
    except Exception as e:  # noqa: BLE001 — record, never raise into the caller
        log.warning("judge failed for %s: %s", call_id, e)
        return {"status": "failed", "model": resolved.model, "fields": None, "error": str(e)}


def _failure(ctx) -> dict | None:
    """Run the failure-analysis LLM (stage 2). Returns its fields, or None if the role
    is unconfigured or it errored — best-effort, never raises."""
    script, guardrails, transcript, call_id, params = ctx
    resolved = resolve_llm(LLMRole.FAILURE_ANALYSIS)
    if resolved is None:
        return None
    try:
        out = analyze_failure(resolved, build_failure_messages(
            script, transcript, guardrails=guardrails, prompt=resolved.prompt, params=params))
        # llm_corrections is a list of pydantic models → plain dicts for the JSON column.
        return {f: [c.model_dump(mode="json") for c in out.llm_corrections]
                if f == "llm_corrections" else getattr(out, f) for f in _FAILURE_FIELDS}
    except Exception as e:  # noqa: BLE001 — failure analysis is best-effort
        log.warning("failure analysis failed for %s: %s", call_id, e)
        return None


def _apply_judge(j: Judgment, res: dict) -> None:
    j.model, j.status, j.error = res["model"], res["status"], res.get("error")
    if res["fields"]:
        for f, v in res["fields"].items():
            setattr(j, f, v)
    else:
        _clear(j, _JUDGE_FIELDS)


def _apply_failure(j: Judgment, fields: dict | None) -> None:
    if fields:
        for f, v in fields.items():
            setattr(j, f, v)
    else:
        _clear(j, _FAILURE_FIELDS)


def _row(db: Session, call: Call) -> Judgment:
    j = db.scalar(select(Judgment).where(Judgment.call_id == call.id))
    if j is None:
        j = Judgment(call_id=call.id)
        db.add(j)
    return j


def _clear(j: Judgment, fields: tuple[str, ...]) -> None:
    for f in fields:
        setattr(j, f, None)


def _params_required(db: Session, call: Call) -> bool:
    """Whether this call's agent gates LLM analysis on per-call params (the manual toggle)."""
    if call.agent_id is None:
        return False
    agent = db.get(Agent, call.agent_id)
    return bool(agent and agent.params_required)


def resolve_params(db: Session, call: Call) -> dict | None:
    """The per-call template parameters for this call, or None. Keyed by the call id the mapper
    resolved to Call.external_call_id (== CallParams.call_key)."""
    if call.agent_id is None:
        return None
    row = db.scalar(select(CallParams).where(
        CallParams.agent_id == call.agent_id, CallParams.call_key == call.external_call_id))
    return row.params if row else None


def _script(db: Session, call: Call) -> str | None:
    if call.prompt_id is None:
        return None
    p = db.get(Prompt, call.prompt_id)
    return p.text if p else None


def _guardrails(db: Session, call: Call) -> str | None:
    """The agent's active guardrails text, or None. Unlike the script, guardrails aren't pinned
    per call — the judge always evaluates against the agent's current active version."""
    if call.agent_id is None:
        return None
    g = db.scalar(select(AgentGuardrail).where(
        AgentGuardrail.agent_id == call.agent_id, AgentGuardrail.active.is_(True)))
    if g is None:
        return None
    p = db.get(Prompt, g.prompt_id)
    return p.text if p else None
