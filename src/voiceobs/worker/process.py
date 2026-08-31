"""One call: fragments -> Trace -> Analysis -> rows."""

from __future__ import annotations

import gzip
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from voiceobs.adapters import UnsupportedSchema, adapter_for
from voiceobs.core.config import METRIC_VERSION
from voiceobs.core.join import join
from voiceobs.core.model import Analysis, CallHeader, Trace
from voiceobs.db.models import Call, Event, IngestRun, Metric, RawFragment
from voiceobs.db.models import Turn as DBTurn

log = logging.getLogger(__name__)

APP_VERSION = "0.0.1"

# core.Turn -> db.Turn where the names differ. Everything else maps by name.
_TURN_RENAMES = {
    "transcript": "caller_transcript",
    "audio_start_s": "caller_utt_end_s",
    "audio_out_start_s": "agent_utt_start_s",
}

# ponytail: one content kind per span row. `clauses` (per-sentence TTS) and `carried`
# are dropped here — join() already folds `carried` into the turn transcript. Give
# Event a kind+text child table if the viewer ever needs per-clause timing.
_PRIMARY_CONTENT = ("transcript", "llm_raw", "llm_spoken")


def assemble(payloads: list[bytes]) -> dict:
    """Gzipped fragments -> one OTLP payload.

    Deduped by spanId: OTLP retries resend spans, and a doubled root would be counted
    twice. Last write wins — a retry carries the more complete span."""
    resource: dict = {}
    spans: dict[str, dict] = {}
    for blob in payloads:
        for rs in json.loads(gzip.decompress(blob)).get("resourceSpans", []):
            resource = resource or rs.get("resource", {})
            for scope in rs.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    spans[span["spanId"]] = span
    return {"resourceSpans": [{"resource": resource,
                               "scopeSpans": [{"spans": list(spans.values())}]}]}


def process(db: Session, call: Call) -> str:
    """Analyse one call and persist the result. Returns the IngestRun status.

    Caller owns the transaction: everything here is one unit, so a crash halfway
    cannot leave a call half-analysed."""
    run = IngestRun(
        call_id=call.id, tenant_id=call.tenant_id, app_version=APP_VERSION,
        metric_version=METRIC_VERSION, status="running", started_at=_now(),
    )
    db.add(run)

    payloads = db.scalars(
        select(RawFragment.payload_gz)
        .where(RawFragment.call_id == call.id)
        .order_by(RawFragment.seq)
    ).all()
    payload = assemble(list(payloads))

    adapter = adapter_for(payload)
    if adapter is None:  # only reachable if the generic adapter is unregistered
        raise UnsupportedSchema("no adapter matched")
    trace = adapter.to_trace(payload)

    # ponytail: spans only — pipe 2 (audio) does not exist yet. join() already takes
    # `audio=None`; pass an AudioAnalysis here once media lands.
    analysis = join(trace, None)

    _persist(db, call, trace, analysis, adapter.version)

    reasons = [r.value for r in analysis.trust.reasons]
    run.status = "partial" if reasons else "ok"
    run.error = ", ".join(reasons) or None
    run.finished_at = _now()
    return run.status


def _persist(
    db: Session, call: Call, trace: Trace, analysis: Analysis, adapter_version: int
) -> None:
    # Delete-then-insert: reprocessing must not double rows, and the unique
    # constraints on turn/metric would reject the second run otherwise.
    for model in (DBTurn, Metric, Event):
        db.execute(delete(model).where(model.call_id == call.id))

    _apply_header(call, trace.header)
    call.unattributed_spans = sum(
        1 for s in trace.spans if s.turn_id is None and s.parent_span_id is not None
    )
    call.metric_version = analysis.metric_version
    call.adapter_version = adapter_version
    call.app_version = APP_VERSION

    db.add_all(
        [_turn_row(t, call, analysis.metric_version) for t in analysis.turns]
        + [_metric_row(m, call, analysis.metric_version) for m in analysis.metrics]
        + list(_event_rows(trace, call))
    )


def _cols(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def _apply_header(call: Call, h: CallHeader) -> None:
    """Copy the adapter's view onto the row. Identity columns are ingest's, not ours:
    renaming a call here would orphan every artifact already posted against it."""
    fields = h.model_dump() | (h.counters or {})
    fields.pop("labels", None)
    for name in _cols(Call) & set(fields):
        if name not in ("id", "tenant_id", "source", "environment"):
            setattr(call, name, fields[name])
    call.labels = h.labels or {}
    call.campaign_id = (h.labels or {}).get("campaign_id")
    if h.started_at and h.ended_at:
        call.duration_s = round((h.ended_at - h.started_at).total_seconds(), 3)


def _turn_row(turn, call: Call, metric_version: int) -> DBTurn:
    d = {_TURN_RENAMES.get(k, k): v for k, v in turn.model_dump().items()}
    return DBTurn(
        call_id=call.id, tenant_id=call.tenant_id, metric_version=metric_version,
        **{k: v for k, v in d.items() if k in _cols(DBTurn)},
    )


def _metric_row(m, call: Call, metric_version: int) -> Metric:
    return Metric(
        call_id=call.id, tenant_id=call.tenant_id, name=m.name,
        value_num=m.value if isinstance(m.value, int | float) else None,
        value_text=m.value if isinstance(m.value, str) else None,
        samples=m.samples, available=m.available, reason=m.reason,
        metric_version=metric_version,
    )


def _event_rows(trace: Trace, call: Call):
    """One row per span, plus one per span event — the timeline the viewer scrubs."""
    for s in trace.spans:
        kind = next((k for k in _PRIMARY_CONTENT if s.content.get(k)), None)
        yield Event(
            call_id=call.id, tenant_id=call.tenant_id, span_id=s.span_id,
            parent_span_id=s.parent_span_id, turn_id=s.turn_id, t_offset_s=s.t_start,
            kind="span", type=s.stage.value, name=s.name, attrs=s.attrs,
            duration_s=None if s.t_end is None else round(s.t_end - s.t_start, 6),
            content_text=s.content.get(kind) if kind else None, content_kind=kind,
        )
        for e in s.events:
            ekind = next(iter(e.content), None)
            yield Event(
                call_id=call.id, tenant_id=call.tenant_id, span_id=s.span_id,
                parent_span_id=s.parent_span_id, turn_id=s.turn_id, t_offset_s=e.t,
                kind="event", type=e.name[:48], name=e.name, attrs=e.attrs,
                content_text=_text(e.content.get(ekind)) if ekind else None,
                content_kind=ekind,
            )


def _text(v) -> str | None:
    """Content is usually a string; a producer may send a list (clause splits)."""
    return " ".join(map(str, v)) if isinstance(v, list) else v


def _now() -> datetime:
    return datetime.now(UTC)
