"""Journey judging for one call — used by `judge_call` when the call's script version has a ready journey
and a decision model is configured; otherwise the classic judge runs unchanged.

Short calls (<= 3 customer turns): one decision-model call -> ShortJudgment.
Longer calls, in parallel:
  - decision model: every judge question + which part of the call each agent turn is in (timeline)
  - LLM: summary, callback time, unscripted moments, wrong values
then, in parallel, the decision model places each failure at its turn (spans) and decides whether the agent
handled each unscripted moment well; the result is merged.
Moments (the line behind each failure) are stored for clustering, and curation (training data) is queued
when the project has it turned on. The classic columns are filled from the result.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete
from sqlalchemy.orm import Session

from voiceobs.config import get_config, resolve_llm
from voiceobs.db.models import Agent, Call, Judgment, Moment
from voiceobs.journey.curate import needs_curation
from voiceobs.journey.decide import render_input, resolve_decision
from voiceobs.journey.handled import handled_input, handled_questions, to_handled
from voiceobs.journey.jev import (
    is_short,
    jev_questions,
    locate_questions,
    short_questions,
    timeline_questions,
    to_judgment,
    to_short,
    to_timeline,
    to_turns,
)
from voiceobs.journey.llm import LLMJudgment, judge_llm, llm_messages
from voiceobs.journey.merge import CallJudgment, apply_llm, merge_decision
from voiceobs.journey.model import Journey
from voiceobs.journey.spans import moment_text, to_locate
from voiceobs.judge.schema import AnsweredBy
from voiceobs.llm import LLMRole
from voiceobs.worker.journey import ready_journey

log = logging.getLogger(__name__)

_RESET = ("script_adherence", "is_failure", "root_cause", "model_fault", "model_fault_detail",
          "hallucination", "hallucination_detail", "suggested_fix")


def try_journey(db: Session, call: Call, j: Judgment, transcript: dict, params: dict | None,
                script: str | None = None) -> bool:
    """Judge `call` the journey way. Returns False (nothing written) when the path doesn't apply."""
    decision = resolve_decision()
    found = ready_journey(db, call.prompt_id) if decision else None
    if not found:
        return False
    version, data = found
    journey = Journey.model_validate(data)
    text = render_input(params, transcript, script)
    lines = transcript.get("lines") or []
    llm_status, llm_error, model = "skipped", None, decision.name
    try:
        if is_short(transcript):
            result = to_short(journey, decision.decide(text, short_questions(journey)))
        else:
            resolved = resolve_llm(LLMRole.JOURNEY_JUDGE)
            qs = jev_questions(journey) + timeline_questions(journey, lines)
            with ThreadPoolExecutor(2) as pool:
                ans_f = pool.submit(decision.decide, text, qs)
                llm_f = pool.submit(judge_llm, resolved, llm_messages(
                    resolved.prompt, json.dumps(data, ensure_ascii=False),
                    render_input(params, transcript))) if resolved else None
                answers = ans_f.result()
                try:
                    llm = llm_f.result() if llm_f else LLMJudgment()
                    llm_status = "ok" if llm_f else "skipped"
                except Exception as e:  # noqa: BLE001 — keep the decision half, note the LLM error
                    llm, llm_status, llm_error = LLMJudgment(), "failed", f"llm: {e}"[:500]
            cj = merge_decision(journey, version, to_judgment(journey, answers), to_timeline(answers, lines))
            at, human = {}, cj.answered_by == AnsweredBy.HUMAN
            todo = to_locate(cj.failures) if human else []
            moments = llm.unscripted if human else []
            with ThreadPoolExecutor(2) as pool:  # where failures happened ‖ were unscripted moments handled
                at_f = pool.submit(decision.decide, text, locate_questions(todo, lines)) if todo else None
                ok_f = pool.submit(decision.decide, handled_input(data, moments, lines),
                                   handled_questions(moments)) if moments else None
                if at_f:
                    at = to_turns(at_f.result(), todo, lines)
                if ok_f:
                    for m, ok in zip(moments, to_handled(ok_f.result(), len(moments)), strict=True):
                        if ok is not None:
                            m.agent_response_ok = ok
            result = apply_llm(cj, journey, llm, at, lines)
            if resolved and llm_f:
                model = f"{decision.name}+{resolved.model}"
    except Exception as e:  # noqa: BLE001 — decision model failed: record, never raise
        log.warning("journey judge failed for %s: %s", call.external_call_id, e)
        j.status, j.error, j.model, j.journey = "failed", f"decision: {e}"[:500], decision.name, None
        j.enrich_status = j.curate_status = None
        return True

    out = result.model_dump(mode="json", by_alias=True)
    j.journey, j.status, j.model, j.error = out, "ok", model, llm_error
    j.enrich_status = llm_status
    fill_classic(j, out)
    curate = False
    if isinstance(result, CallJudgment):
        store_moments(db, call, result, lines)
        agent = db.get(Agent, call.agent_id) if call.agent_id else None
        curate = bool(agent and agent.curate_training_data and get_config().curate_enabled
                      and needs_curation(result))
    j.curate_status = "pending" if curate else "skipped"
    return True


def store_moments(db: Session, call: Call, cj: CallJudgment, lines: list[dict]) -> int:
    """One `moment` per located failure (what the Clusters tab embeds and clusters); replaces the call's."""
    db.execute(delete(Moment).where(Moment.call_id == call.id))
    ok = {(u.turn, u.what): u.agent_response_ok for u in cj.unscripted}
    seen, n = set(), 0
    for f in cj.failures:
        found = moment_text(f, lines)
        if found is None or (f.kind, f.item, found[0]) in seen:
            continue
        seen.add((f.kind, f.item, found[0]))
        handled = ok.get((f.turns[0], f.item)) if f.kind == "unscripted" and f.turns else None
        db.add(Moment(call_id=call.id, agent_id=call.agent_id or "", prompt_id=call.prompt_id, kind=f.kind,
                      item=f.item, cause=f.cause, turn=found[0], text=found[1][:2000], handled=handled))
        n += 1
    return n


def fill_classic(j: Judgment, r: dict) -> None:
    """Mirror the journey result into the classic judgment columns (boards, clusters, exports)."""
    for f in _RESET:
        setattr(j, f, None)
    j.answered_by = r.get("answered_by")
    j.primary_language = r.get("primary_language") or (r.get("language") or {}).get("primary")
    j.secondary_languages = (r.get("language") or {}).get("secondary", [])
    j.objective_achieved = r.get("objective_achieved")
    j.sentiment = r.get("sentiment")
    j.summary = r.get("summary")
    broken = r.get("guardrails_broken") or []
    j.guardrail_violation = bool(broken)
    j.guardrail_violation_points = [g["rule"] for g in broken]
    st = r.get("standard") or {}
    j.callback_requested = bool(st.get("callback_requested"))
    j.callback_time = st.get("callback_time")
    j.escalation_requested = bool(st.get("escalation_requested"))
    j.llm_corrections = []  # journey training data lives in training_sample (stage 3)
