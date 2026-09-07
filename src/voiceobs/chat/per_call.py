"""Per-call chat: build a bounded system prompt for one call. The transcript, computed metrics, and
LLM analysis are small enough to dump inline; the large span/event trace is NOT — the agent reaches
it with `execute_sql` over the `events` table, filtered to this call. No pgvector skill, no full
schema doc — just this call's context plus a one-table note.

Assembled straight from the DB (models + voiceobs.transcript) so `chat` never imports `api`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs import transcript as transcript_mod
from voiceobs.db.models import Call, Judgment, Metric

# Judgment fields worth putting in front of the model (skip plumbing: id/model/error/timestamps).
_JUDGE_FIELDS = (
    "disposition", "sentiment", "objective_achieved", "answered_by", "primary_language",
    "script_adherence", "escalation_requested", "callback_requested", "callback_time",
    "guardrail_violation", "guardrail_violation_points", "is_failure", "root_cause",
    "model_fault", "model_fault_detail", "hallucination", "hallucination_detail",
    "suggested_fix", "summary",
)

_EVENTS_NOTE = """\
For the raw span/event trace of THIS call (per-stage timings, errors, span content), call the
`execute_sql` tool over the `events` table and ALWAYS filter to this call:

  events(call_id, span_id, parent_span_id, turn_id, t_offset_s, kind /* 'span'|'event' */,
         type /* 'stt'|'llm'|'tts'|… */, name, duration_s /* seconds */, error /* bool */,
         content_text, content_kind)

Always include `WHERE call_id = '{call_id}'` and a LIMIT. That is the only table you should query;
everything else about the call is already given above.\
"""


def _transcript_block(db: Session, call: Call) -> str:
    t = transcript_mod.resolve(db, call)
    if t.get("format") == "turns":
        lines = t.get("lines") or []
        if not lines:
            return "(no transcript available)"
        return "\n".join(f"[{ln['turn_index']}] {ln['role']}: {ln['text']}" for ln in lines)
    return (t.get("text") or "(no transcript available)").strip()


def _metrics_block(db: Session, call: Call) -> str:
    rows = db.scalars(select(Metric).where(Metric.call_id == call.id)).all()
    vals = [(m.name, m.value_num if m.value_num is not None else m.value_text)
            for m in rows if m.available]
    if not vals:
        return "(no computed metrics)"
    return "\n".join(f"- {name}: {value}" for name, value in vals)


def _judgment_block(db: Session, call: Call) -> str:
    j = db.scalar(select(Judgment).where(Judgment.call_id == call.id))
    if j is None:
        return "(not analysed)"
    out = []
    for f in _JUDGE_FIELDS:
        v = getattr(j, f, None)
        if v not in (None, "", [], False):
            out.append(f"- {f}: {v}")
    return "\n".join(out) or "(analysis produced no notable findings)"


def build_per_call_prompt(db: Session, call: Call, persona: str) -> str:
    """persona + this call's transcript, metrics, and LLM analysis, plus the events-table note."""
    return (
        f"{persona}\n\n"
        f"You are focused on a SINGLE call (external id: {call.external_call_id}). "
        f"Answer from the context below; use the tool only for span-level detail.\n\n"
        f"=== CALL {call.external_call_id} ===\n"
        f"agent_id: {call.agent_id}  status: {call.status}  duration_s: {call.duration_s}  "
        f"engine: {call.engine}  providers: stt={call.stt_provider} llm={call.llm_provider} "
        f"tts={call.tts_provider}\n\n"
        f"--- Transcript ---\n{_transcript_block(db, call)}\n\n"
        f"--- Computed metrics ---\n{_metrics_block(db, call)}\n\n"
        f"--- LLM analysis (judgment) ---\n{_judgment_block(db, call)}\n\n"
        f"--- Span/event trace (via tool) ---\n{_EVENTS_NOTE.format(call_id=call.id)}"
    )
