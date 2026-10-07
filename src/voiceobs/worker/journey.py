"""Journey extraction: one journey per script version (Prompt), extracted in the background.

Saving a new script version queues a `pending` AgentJourney (`ensure_pending`); the backfill worker's loop
calls `run_pending` per org schema, which runs the script -> journey LLM (`journey.extract`) and stores
the result as `ready` (or `failed` with the error). Identical script text shares one Prompt, so it is
never extracted twice.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.db.models import AgentJourney, Prompt

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def ensure_pending(db: Session, prompt_id: str, *, force: bool = False) -> AgentJourney:
    """Queue extraction for a script version unless it already has a journey (or `force`)."""
    row = db.scalar(select(AgentJourney).where(AgentJourney.prompt_id == prompt_id))
    if row is None:
        row = AgentJourney(prompt_id=prompt_id, status="pending")
        db.add(row)
    elif force:
        row.status, row.error, row.edited, row.updated_at = "pending", None, False, _now()
    db.flush()
    return row


def ready_journey(db: Session, prompt_id: str | None) -> tuple[str, dict] | None:
    """(journey row id, journey JSON) for a script version, if extracted and ready."""
    if not prompt_id:
        return None
    row = db.scalar(select(AgentJourney).where(AgentJourney.prompt_id == prompt_id,
                                               AgentJourney.status == "ready"))
    return (row.id, row.journey) if row and row.journey else None


def extract_one(db: Session, row: AgentJourney, structured=None, prompt: str | None = None) -> None:
    """Run extraction for one row and store the outcome. `structured`/`prompt` default to Pulse's LLM."""
    from voiceobs.journey.extract import extract_journey, pulse_structured

    text = db.scalar(select(Prompt.text).where(Prompt.id == row.prompt_id)) or ""
    try:
        if structured is None:
            structured, prompt = pulse_structured()
        journey, draft = extract_journey(text, structured, prompt or "")
        row.journey = journey.model_dump(mode="json", by_alias=True)
        row.draft = draft.model_dump(mode="json", by_alias=True)
        row.status, row.error = "ready", None
        row.model = getattr(structured, "model_name", None) or "script_journey"
    except Exception as e:  # noqa: BLE001 — record, never crash the worker loop
        log.warning("journey extraction failed for prompt %s: %s", row.prompt_id, e)
        row.status, row.error = "failed", str(e)[:2000]
    row.updated_at = _now()


def run_pending(db: Session, limit: int = 5) -> int:
    """Extract up to `limit` pending journeys in the current schema. Returns how many were processed."""
    done = 0
    for _ in range(limit):
        row = db.scalar(select(AgentJourney).where(AgentJourney.status == "pending")
                        .order_by(AgentJourney.created_at))
        if row is None:
            break
        row.status, row.updated_at = "extracting", _now()
        db.commit()
        extract_one(db, row)
        db.commit()
        done += 1
    return done
