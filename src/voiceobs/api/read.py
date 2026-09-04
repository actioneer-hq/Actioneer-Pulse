"""Read endpoints for the viewer. Serve DB state; turns/metrics fill in once the
worker runs."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.auth import current_membership, get_scoped_call, visible_agent_ids
from voiceobs.core.config import METRIC_DEFS
from voiceobs.db.models import AudioDiscrepancy, Call, Event, Media, Membership, Metric, Turn
from voiceobs.storage import presign, resolve_s3_creds
from voiceobs.transcript import resolve

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")


@router.get("/calls")
def list_calls(
    mem: Membership = Depends(current_membership),
    db: Session = Depends(session_dep),
    environment: str | None = None,
    status: str | None = None,
    q: str | None = None,
    agent_id: str | None = None,
    limit: int = Query(50, le=200),
) -> dict:
    stmt = (
        select(Call)
        .where(Call.tenant_id == mem.org_id)  # never leak across orgs
        # nulls_last: an unprocessed call has no started_at yet and would otherwise
        # sort to the top of every list forever.
        .order_by(Call.started_at.desc().nulls_last(), Call.created_at.desc())
        .limit(limit)
    )
    ids = visible_agent_ids(db, mem)  # None = all org agents (coarse); else restricted
    if ids is not None:
        stmt = stmt.where(Call.agent_id.in_(ids))
    if agent_id:  # explicit filter, still bounded by the RBAC scope above
        stmt = stmt.where(Call.agent_id == agent_id)
    if environment:
        stmt = stmt.where(Call.environment == environment)
    if status:
        stmt = stmt.where(Call.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Call.external_call_id.ilike(like) | Call.source.ilike(like))
    calls = db.scalars(stmt).all()
    stats = _turn_stats(db, [c.id for c in calls])
    return {"items": [_list_item(c, stats.get(c.id)) for c in calls]}


def _turn_stats(db: Session, call_ids: list[str]) -> dict[str, dict]:
    """Per-call turn count, barge-ins and median voice-to-voice, in one query. The
    percentile is taken in Python so SQLite tests and Postgres agree."""
    if not call_ids:
        return {}
    rows = db.execute(
        select(Turn.call_id, Turn.interrupted, Turn.response_latency_ms)
        .where(Turn.call_id.in_(call_ids))
    ).all()
    out: dict[str, dict] = {}
    for call_id, interrupted, v2v in rows:
        s = out.setdefault(call_id, {"turns": 0, "barge_ins": 0, "v2v": []})
        s["turns"] += 1
        if interrupted:
            s["barge_ins"] += 1
        elif v2v is not None:
            s["v2v"].append(v2v)
    for s in out.values():
        v = sorted(s.pop("v2v"))
        s["p50_v2v_ms"] = v[len(v) // 2] if v else None
    return out


@router.get("/calls/{call_id}")
def get_call(
    call: Call = Depends(get_scoped_call), db: Session = Depends(session_dep)
) -> dict:
    """The whole analysis for one call in a single round trip: header, turns,
    metrics, trust, the span/waterfall tree, waveform peaks, and a presigned audio
    URL. Audio bytes are streamed by the browser from that URL, never through here."""
    turns = db.scalars(
        select(Turn).where(Turn.call_id == call.id).order_by(Turn.turn_index)
    ).all()
    metrics = db.scalars(select(Metric).where(Metric.call_id == call.id)).all()
    media = db.scalars(select(Media).where(Media.call_id == call.id)).all()
    events = db.scalars(
        select(Event).where(Event.call_id == call.id).order_by(Event.t_offset_s)
    ).all()
    return {
        "call": _header(call),
        "turns": [_turn(t) for t in turns],
        "metrics": [_metric(m) for m in metrics],
        "trust": _trust(call, metrics),
        "spans": _span_tree(events),
        "peaks": _peaks(media),
        "audio": _audio(call, media, db),
        "discrepancies": _discrepancies(db, call),
        "versions": {
            "metric_version": call.metric_version,
            "adapter_version": call.adapter_version,
            "app_version": call.app_version,
        },
    }


@router.get("/calls/{call_id}/transcript")
def get_transcript(
    call: Call = Depends(get_scoped_call), db: Session = Depends(session_dep)
) -> dict:
    """BYO transcript if uploaded, else derived from turn content. Feeds the judge."""
    return resolve(db, call)


@router.get("/metric-defs")
def metric_defs() -> list[dict]:
    return [d.model_dump() for d in METRIC_DEFS]


def _list_item(c: Call, stats: dict | None) -> dict:
    stats = stats or {"turns": 0, "barge_ins": 0, "p50_v2v_ms": None}
    return {
        "id": c.external_call_id,
        "started_at": c.started_at,
        "duration_s": c.duration_s,
        "environment": c.environment,
        "source": c.source,
        "labels": c.labels or {},
        "status": c.status,
        "media_ready": c.media_ready,
        "analysed": c.metric_version is not None,
        **stats,
    }


_CALL_SKIP = {"id", "tenant_id", "prompt_id"}


def _header(c: Call) -> dict:
    """Same reasoning as _turn: hand-listing columns is how fields the worker fills
    never reach the viewer."""
    return {"id": c.external_call_id} | {
        col.name: getattr(c, col.name)
        for col in Call.__table__.columns
        if col.name not in _CALL_SKIP
    }


# Everything the worker fills, minus the FK/tenant plumbing. Listing columns by hand
# is how half the waterfall silently never reached the viewer.
_TURN_SKIP = {"id", "call_id", "tenant_id"}


def _turn(t: Turn) -> dict:
    return {c.name: getattr(t, c.name)
            for c in Turn.__table__.columns if c.name not in _TURN_SKIP}


def _metric(m: Metric) -> dict:
    return {
        "name": m.name,
        "value": m.value_num if m.value_num is not None else m.value_text,
        "samples": m.samples,
        "available": m.available,
        "reason": m.reason,
    }


def _trust(call: Call, metrics: list[Metric]) -> dict:
    cov = next((m for m in metrics if m.name == "capture_coverage"), None)
    return {
        "spans_complete": call.spans_complete,
        "media_ready": call.media_ready,
        "audio_analysis": cov is not None,  # the opt-in overlay ran (else OTLP-only)
        "capture_coverage": cov.samples if cov and cov.samples else {},
        "span_dropped_events": call.span_dropped_events,
        "unattributed_spans": call.unattributed_spans,
    }


def _span_tree(events: list[Event]) -> list[dict]:
    """Flat spans (with nested events) ordered by start — the client nests via
    parent_span_id. This is the waterfall the viewer draws."""
    by_span: dict[str, list] = {}
    for e in events:
        if e.kind == "event":
            by_span.setdefault(e.span_id, []).append({
                "name": e.name, "t_offset_s": e.t_offset_s,
                "attrs": e.attrs or {}, "content_text": e.content_text,
            })
    return [{
        "span_id": e.span_id,
        "parent_span_id": e.parent_span_id,
        "name": e.name,
        "stage": e.type,
        "turn_id": e.turn_id,
        "t_start_s": e.t_offset_s,
        "duration_s": e.duration_s,
        "attrs": e.attrs or {},
        "content_text": e.content_text,
        "content_kind": e.content_kind,
        "events": by_span.get(e.span_id, []),
    } for e in events if e.kind == "span"]


def _peaks(media: list[Media]) -> dict[str, str]:
    """Per-channel waveform peaks, base64. Small enough to embed; the waveform draws
    from these, not the WAV."""
    out: dict[str, str] = {}
    for m in media:
        if m.kind.startswith("peaks_") and m.peaks:
            out[m.kind.removeprefix("peaks_")] = base64.b64encode(m.peaks).decode()
    return out


def _discrepancies(db: Session, call: Call) -> list[dict]:
    """Ground-truth vs reported: where the audio disagrees with the OTLP self-report."""
    rows = db.scalars(
        select(AudioDiscrepancy).where(AudioDiscrepancy.call_id == call.id)
        .order_by(AudioDiscrepancy.turn_index)
    ).all()
    return [{
        "turn_index": r.turn_index, "dimension": r.dimension, "field": r.field,
        "reported": r.reported, "measured": r.measured, "delta": r.delta,
        "band": r.band, "verdict": r.verdict, "note": r.note,
    } for r in rows]


def _audio(call: Call, media: list[Media], db: Session) -> dict | None:
    wav = next((m for m in media if m.kind == "audio" and m.uri), None)
    if wav is None:
        return None
    try:
        url = presign(wav.uri, creds=resolve_s3_creds(db, call.agent_id))
    except Exception as e:  # noqa: BLE001 — a presign failure must not 500 the analysis
        log.warning("presign failed for %s: %s", call.external_call_id, e)
        url = None
    return {"url": url, "sample_rate": wav.sample_rate, "channels": wav.channels,
            "duration_s": call.duration_s}
