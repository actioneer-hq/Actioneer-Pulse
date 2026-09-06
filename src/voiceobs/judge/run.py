"""Judge one call: disposition (always) + two LLM passes on connected calls — the post-call
judge (JudgeOutput) and, alongside it, a failure-analysis LLM (FailureAnalysis) for root cause.
Own transaction; neither model failure ever touches the metrics or raises into the caller."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import resolve_llm
from voiceobs.db.models import AgentGuardrail, Call, Judgment, Prompt
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
    "hallucination", "hallucination_detail", "suggested_fix",
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

    script, guardrails = _script(db, call), _guardrails(db, call)
    _run_judge(j, script, guardrails, transcript, call)
    _run_failure(j, script, guardrails, transcript, call)  # second LLM, alongside the judge
    return j


def _run_judge(j: Judgment, script, guardrails, transcript, call: Call) -> None:
    resolved = resolve_llm(LLMRole.POST_CALL_ANALYSIS)
    if resolved is None:  # role not configured (no API key) → skip the LLM pass
        _clear(j, _JUDGE_FIELDS)
        j.status, j.model = "skipped", None
        return
    j.model = resolved.model
    try:
        out = call_model(resolved, build_messages(
            script, transcript, guardrails=guardrails, prompt=resolved.prompt))
        for f in _JUDGE_FIELDS:
            setattr(j, f, getattr(out, f))
        j.status, j.error = "ok", None
    except Exception as e:  # noqa: BLE001 — record, never raise into the caller
        log.warning("judge failed for %s: %s", call.external_call_id, e)
        _clear(j, _JUDGE_FIELDS)
        j.status, j.error = "failed", str(e)


def _run_failure(j: Judgment, script, guardrails, transcript, call: Call) -> None:
    """Independent failure-analysis pass. Never raises; leaves the columns null on skip/error."""
    resolved = resolve_llm(LLMRole.FAILURE_ANALYSIS)
    if resolved is None:  # not configured → leave the failure columns null
        _clear(j, _FAILURE_FIELDS)
        return
    try:
        out = analyze_failure(resolved, build_failure_messages(
            script, transcript, guardrails=guardrails, prompt=resolved.prompt))
        for f in _FAILURE_FIELDS:
            setattr(j, f, getattr(out, f))
    except Exception as e:  # noqa: BLE001 — failure analysis is best-effort
        log.warning("failure analysis failed for %s: %s", call.external_call_id, e)
        _clear(j, _FAILURE_FIELDS)


def _row(db: Session, call: Call) -> Judgment:
    j = db.scalar(select(Judgment).where(Judgment.call_id == call.id))
    if j is None:
        j = Judgment(call_id=call.id, tenant_id=call.tenant_id)
        db.add(j)
    return j


def _clear(j: Judgment, fields: tuple[str, ...]) -> None:
    for f in fields:
        setattr(j, f, None)


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
