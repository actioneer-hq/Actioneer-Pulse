"""Judge one call: disposition (always) + two LLM passes on connected calls — the post-call
judge (JudgeOutput) and, in parallel, a failure-analysis LLM (FailureAnalysis) for root cause.

The two models are network-bound and independent, so they run concurrently in a thread pool;
each returns plain results and ALL DB/ORM mutation happens on this (main) thread afterwards, so
the Session is never touched off-thread. Own transaction; neither model failure raises."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

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

    # DB reads happen here on the main thread; the LLM passes below get plain args.
    script, guardrails = _script(db, call), _guardrails(db, call)
    ctx = (script, guardrails, transcript, call.external_call_id)

    # Both models are network-bound and independent → run them at the same time.
    with ThreadPoolExecutor(max_workers=2) as ex:
        judge_future = ex.submit(_judge, ctx)
        failure_future = ex.submit(_failure, ctx)
        judge_res = judge_future.result()
        failure_res = failure_future.result()

    _apply_judge(j, judge_res)
    _apply_failure(j, failure_res)
    return j


def _judge(ctx) -> dict:
    """Run the post-call judge (in a worker thread). Pure: returns results, never touches the DB."""
    script, guardrails, transcript, call_id = ctx
    resolved = resolve_llm(LLMRole.POST_CALL_ANALYSIS)
    if resolved is None:  # role not configured (no API key)
        return {"status": "skipped", "model": None, "fields": None, "error": None}
    try:
        out = call_model(resolved, build_messages(
            script, transcript, guardrails=guardrails, prompt=resolved.prompt))
        return {"status": "ok", "model": resolved.model,
                "fields": {f: getattr(out, f) for f in _JUDGE_FIELDS}, "error": None}
    except Exception as e:  # noqa: BLE001 — record, never raise into the caller
        log.warning("judge failed for %s: %s", call_id, e)
        return {"status": "failed", "model": resolved.model, "fields": None, "error": str(e)}


def _failure(ctx) -> dict | None:
    """Run the failure-analysis LLM (in a worker thread). Returns its fields, or None if the role
    is unconfigured or it errored — best-effort, never raises."""
    script, guardrails, transcript, call_id = ctx
    resolved = resolve_llm(LLMRole.FAILURE_ANALYSIS)
    if resolved is None:
        return None
    try:
        out = analyze_failure(resolved, build_failure_messages(
            script, transcript, guardrails=guardrails, prompt=resolved.prompt))
        return {f: getattr(out, f) for f in _FAILURE_FIELDS}
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
