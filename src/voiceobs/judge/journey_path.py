"""Journey judging for one call, stage 1 — used by `judge_call` when the call's script version has a ready
journey and a decision model is configured; otherwise the classic judge runs unchanged.

Stage 1 (here, in the judge worker): the decision model only, so results land in seconds.
Short calls (<= 3 customer turns) -> ShortJudgment, done. Longer calls -> CallJudgment with the LLM fields
empty and `enrich_status = pending`: stage 2 (journey/enrich.py) adds summary, timeline and spans, and
stage 3 (journey/curate.py) the training data, both from the journey-llm worker.
The result is stored in `judgment.journey`; the classic columns are filled from it so boards, clusters
and exports keep working.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from voiceobs.db.models import Call, Judgment
from voiceobs.journey.decide import render_input, resolve_decision
from voiceobs.journey.jev import is_short, jev_questions, short_questions, to_judgment, to_short
from voiceobs.journey.merge import merge_decision
from voiceobs.journey.model import Journey
from voiceobs.judge.schema import AnsweredBy
from voiceobs.worker.journey import ready_journey

log = logging.getLogger(__name__)

_RESET = ("script_adherence", "is_failure", "root_cause", "model_fault", "model_fault_detail",
          "hallucination", "hallucination_detail", "suggested_fix")


def try_journey(db: Session, call: Call, j: Judgment, transcript: dict, params: dict | None,
                script: str | None = None) -> bool:
    """Judge `call` the journey way (stage 1). Returns False (nothing written) when the path doesn't
    apply."""
    decision = resolve_decision()
    found = ready_journey(db, call.prompt_id) if decision else None
    if not found:
        return False
    version, data = found
    journey = Journey.model_validate(data)
    text = render_input(params, transcript, script)
    try:
        if is_short(transcript):
            result = to_short(journey, decision.decide(text, short_questions(journey)))
            enrich = "skipped"
        else:
            result = merge_decision(journey, version, to_judgment(journey, decision.decide(
                text, jev_questions(journey))))
            enrich = "pending" if result.answered_by == AnsweredBy.HUMAN else "skipped"
    except Exception as e:  # noqa: BLE001 — decision model failed: record, never raise
        log.warning("journey judge failed for %s: %s", call.external_call_id, e)
        j.status, j.error, j.model, j.journey = "failed", f"decision: {e}"[:500], decision.name, None
        j.enrich_status = j.curate_status = None
        return True

    out = result.model_dump(mode="json", by_alias=True)
    j.journey = out
    j.status, j.model, j.error = "ok", decision.name, None
    j.enrich_status, j.curate_status = enrich, "skipped"
    fill_classic(j, out)
    return True


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
