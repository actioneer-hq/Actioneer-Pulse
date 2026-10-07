"""Journey stages 2 and 3 for one call, run by the journey-llm worker after stage 1 (journey_path.py).

Stage 2 (`enrich_call`): the LLM adds summary, callback time, unscripted moments, wrong values and the
timeline, which gives every failure its span; then stage 3 is queued if a `not_followed` failure has an
agent turn to correct. Stage 3 (`curate_call`): corrections for those turns -> `training_sample`.
Both are idempotent and keep the stage-1 result if their LLM call fails.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from voiceobs.config import get_config, resolve_llm
from voiceobs.db.models import Call, Judgment, TrainingSample
from voiceobs.journey.curate import curate, needs_curation
from voiceobs.journey.decide import render_input
from voiceobs.journey.llm import judge_llm, llm_messages
from voiceobs.journey.merge import CallJudgment, apply_llm
from voiceobs.journey.model import Journey
from voiceobs.journey.spans import describe
from voiceobs.judge.journey_path import fill_classic
from voiceobs.llm import LLMRole
from voiceobs.transcript import resolve
from voiceobs.worker.journey import ready_journey

log = logging.getLogger(__name__)


def _judgment(db: Session, call: Call) -> Judgment | None:
    return db.scalar(select(Judgment).where(Judgment.call_id == call.id))


def enrich_call(db: Session, call: Call) -> bool:
    """Run stage 2 for `call`. Returns True when stage 3 should be queued."""
    from voiceobs.judge.run import resolve_params

    j = _judgment(db, call)
    if j is None or not j.journey or j.journey.get("format") != "full" or j.enrich_status in ("ok", "skipped"):
        return False
    found, resolved = ready_journey(db, call.prompt_id), resolve_llm(LLMRole.JOURNEY_JUDGE)
    if not found or resolved is None:
        j.enrich_status = "skipped"
        return False
    data = found[1]
    journey, cj = Journey.model_validate(data), CallJudgment.model_validate(j.journey)
    transcript = resolve(db, call)
    j.enrich_status = "running"
    db.flush()
    text = render_input(resolve_params(db, call), transcript)
    block = describe(journey, [f for f in cj.failures if f.kind != "unscripted"])
    try:
        llm = judge_llm(resolved, llm_messages(resolved.prompt, json.dumps(data, ensure_ascii=False),
                                               f"{text}\n\n{block}" if block else text))
    except Exception as e:  # noqa: BLE001 — keep the stage-1 result, mark the stage failed
        log.warning("journey enrich failed for %s: %s", call.external_call_id, e)
        j.enrich_status, j.error = "failed", f"enrich: {e}"[:500]
        return False
    cj = apply_llm(cj, journey, llm, transcript.get("lines") or [])
    out = cj.model_dump(mode="json", by_alias=True)
    j.journey, j.enrich_status, j.error = out, "ok", None
    if j.model and resolved.model not in j.model:
        j.model = f"{j.model}+{resolved.model}"
    fill_classic(j, out)
    then = get_config().curate_enabled and needs_curation(cj)
    j.curate_status = "pending" if then else "skipped"
    return then


def curate_call(db: Session, call: Call) -> int:
    """Run stage 3 for `call`; returns how many training samples were stored."""
    from voiceobs.judge.run import resolve_params

    j = _judgment(db, call)
    if j is None or not j.journey or j.curate_status in ("ok", "skipped", None):
        return 0
    found, resolved = ready_journey(db, call.prompt_id), resolve_llm(LLMRole.TRAINING_CURATOR)
    if not found or resolved is None:
        j.curate_status = "skipped"
        return 0
    j.curate_status = "running"
    db.flush()
    try:
        samples = curate(resolved, json.dumps(found[1], ensure_ascii=False), Journey.model_validate(found[1]),
                         CallJudgment.model_validate(j.journey), resolve_params(db, call), resolve(db, call))
    except Exception as e:  # noqa: BLE001 — no training data beats unchecked training data
        log.warning("journey curate failed for %s: %s", call.external_call_id, e)
        j.curate_status = "failed"
        return 0
    db.execute(delete(TrainingSample).where(TrainingSample.call_id == call.id))
    for s in samples:
        db.add(TrainingSample(call_id=call.id, prompt_id=call.prompt_id, model=resolved.model, **s))
    j.curate_status = "ok"
    return len(samples)
