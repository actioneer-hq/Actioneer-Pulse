"""Judge one call: disposition (always) + the LLM output (only when connected and a
model is configured). Own transaction — a model failure never touches the metrics."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import resolve_llm
from voiceobs.db.models import Call, Judgment, Prompt
from voiceobs.judge.client import call_model
from voiceobs.judge.disposition import is_connected, programmatic_disposition
from voiceobs.judge.prompt import build_messages
from voiceobs.llm import LLMRole
from voiceobs.transcript import resolve

log = logging.getLogger(__name__)

_LLM_FIELDS = (
    "sentiment", "objective_achieved", "answered_by", "primary_language",
    "secondary_languages", "script_adherence", "escalation_requested",
    "callback_requested", "callback_time", "summary",
)


def judge_call(db: Session, call: Call) -> Judgment:
    transcript = resolve(db, call)
    disposition = programmatic_disposition(call, transcript)
    j = _row(db, call)
    j.disposition = disposition

    if not is_connected(disposition):
        _clear_llm(j)
        j.status, j.model = "skipped", None
        return j

    resolved = resolve_llm(LLMRole.POST_CALL_ANALYSIS)
    if resolved is None:  # role not configured (no API key set) → skip the LLM pass
        _clear_llm(j)
        j.status, j.model = "skipped", None
        return j

    j.model = resolved.model
    try:
        out = call_model(resolved, build_messages(
            _script(db, call), transcript, prompt=resolved.prompt,
        ))
        for f in _LLM_FIELDS:
            setattr(j, f, getattr(out, f))
        j.status, j.error = "ok", None
    except Exception as e:  # noqa: BLE001 — record, never raise into the caller
        log.warning("judge failed for %s: %s", call.external_call_id, e)
        _clear_llm(j)
        j.status, j.error = "failed", str(e)
    return j


def _row(db: Session, call: Call) -> Judgment:
    j = db.scalar(select(Judgment).where(Judgment.call_id == call.id))
    if j is None:
        j = Judgment(call_id=call.id, tenant_id=call.tenant_id)
        db.add(j)
    return j


def _clear_llm(j: Judgment) -> None:
    for f in _LLM_FIELDS:
        setattr(j, f, None)


def _script(db: Session, call: Call) -> str | None:
    if call.prompt_id is None:
        return None
    p = db.get(Prompt, call.prompt_id)
    return p.text if p else None
