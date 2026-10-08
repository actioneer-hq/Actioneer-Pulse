"""Journey curation for one call (training data), run by the journey-llm worker after the judge.

`curate_call`: corrections for the call's failed agent turns -> `training_sample`. Only queued when the
call's project has data curation turned on. Idempotent; keeps nothing if the LLM call fails.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from voiceobs.config import resolve_llm
from voiceobs.db.models import Call, Judgment, TrainingSample
from voiceobs.journey.curate import curate
from voiceobs.journey.merge import CallJudgment
from voiceobs.journey.model import Journey
from voiceobs.llm import LLMRole
from voiceobs.transcript import resolve
from voiceobs.worker.journey import ready_journey

log = logging.getLogger(__name__)


def curate_call(db: Session, call: Call) -> int:
    """Correct the call's failed agent turns; returns how many training samples were stored."""
    from voiceobs.judge.run import resolve_params

    j = db.scalar(select(Judgment).where(Judgment.call_id == call.id))
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
