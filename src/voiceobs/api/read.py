"""Read endpoints for the viewer. Serve DB state; turns/metrics fill in once the
worker runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.core.config import METRIC_DEFS
from voiceobs.db.models import Call, Event, Media, Metric, Turn

router = APIRouter(prefix="/v1")


@router.get("/calls")
def list_calls(
    db: Session = Depends(session_dep),
    environment: str | None = None,
    status: str | None = None,
    limit: int = Query(50, le=200),
) -> dict:
    turns = (
        select(func.count(Turn.id))
        .where(Turn.call_id == Call.id)
        .correlate(Call)
        .scalar_subquery()
    )
    stmt = (
        select(Call, turns)
        # nulls_last: an unprocessed call has no started_at yet and would otherwise
        # sort to the top of every list forever.
        .order_by(Call.started_at.desc().nulls_last(), Call.created_at.desc())
        .limit(limit)
    )
    if environment:
        stmt = stmt.where(Call.environment == environment)
    if status:
        stmt = stmt.where(Call.status == status)
    return {"items": [_list_item(c, n) for c, n in db.execute(stmt)]}


@router.get("/calls/{call_id}")
def get_call(call_id: str, db: Session = Depends(session_dep)) -> dict:
    call = _get_call(db, call_id)
    turns = db.scalars(
        select(Turn).where(Turn.call_id == call.id).order_by(Turn.turn_index)
    ).all()
    metrics = db.scalars(select(Metric).where(Metric.call_id == call.id)).all()
    media = db.scalars(select(Media).where(Media.call_id == call.id)).all()
    return {
        "call": _header(call),
        "turns": [_turn(t) for t in turns],
        "metrics": [_metric(m) for m in metrics],
        "trust": {
            "spans_complete": call.spans_complete,
            "media_ready": call.media_ready,
            "capture_coverage": {},
        },
        "media": [{"kind": m.kind, "channels": m.channels, "sample_rate": m.sample_rate}
                  for m in media],
        "versions": {
            "metric_version": call.metric_version,
            "adapter_version": call.adapter_version,
            "app_version": call.app_version,
        },
    }


@router.get("/calls/{call_id}/spans")
def get_spans(call_id: str, db: Session = Depends(session_dep)) -> dict:
    """The waterfall: every span with its length, each one's events nested under it.

    Flat, with parent_span_id — the client nests it. Ordering by start time means a
    depth-first render needs no sort."""
    call = _get_call(db, call_id)
    rows = db.scalars(
        select(Event).where(Event.call_id == call.id).order_by(Event.t_offset_s)
    ).all()

    events: dict[str, list] = {}
    for e in rows:
        if e.kind == "event":
            events.setdefault(e.span_id, []).append({
                "name": e.name, "t_offset_s": e.t_offset_s,
                "attrs": e.attrs or {}, "content_text": e.content_text,
            })
    return {
        "call_id": call.external_call_id,
        "source": call.source,
        "duration_s": call.duration_s,
        "spans": [{
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
            "events": events.get(e.span_id, []),
        } for e in rows if e.kind == "span"],
    }


@router.get("/metric-defs")
def metric_defs() -> list[dict]:
    return [d.model_dump() for d in METRIC_DEFS]


def _get_call(db: Session, call_id: str) -> Call:
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        raise HTTPException(404, "call not found")
    return call


def _list_item(c: Call, turns: int = 0) -> dict:
    return {
        "id": c.external_call_id,
        "started_at": c.started_at,
        "duration_s": c.duration_s,
        "environment": c.environment,
        "source": c.source,
        "labels": c.labels or {},
        "status": c.status,
        "turns": turns,
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
