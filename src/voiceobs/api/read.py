"""Read endpoints for the viewer. Serve DB state; turns/metrics fill in once the
worker runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.deps import session_dep
from voiceobs.core.config import METRIC_DEFS
from voiceobs.db.models import Call, Media, Metric, Turn

router = APIRouter(prefix="/v1")


@router.get("/calls")
def list_calls(
    db: Session = Depends(session_dep),
    environment: str | None = None,
    status: str | None = None,
    limit: int = Query(50, le=200),
) -> dict:
    stmt = select(Call).order_by(Call.started_at.desc()).limit(limit)
    if environment:
        stmt = stmt.where(Call.environment == environment)
    if status:
        stmt = stmt.where(Call.status == status)
    return {"items": [_list_item(c) for c in db.scalars(stmt)]}


@router.get("/calls/{call_id}")
def get_call(call_id: str, db: Session = Depends(session_dep)) -> dict:
    call = db.scalar(select(Call).where(Call.external_call_id == call_id))
    if call is None:
        raise HTTPException(404, "call not found")
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


@router.get("/metric-defs")
def metric_defs() -> list[dict]:
    return [d.model_dump() for d in METRIC_DEFS]


def _list_item(c: Call) -> dict:
    return {
        "id": c.external_call_id,
        "started_at": c.started_at,
        "duration_s": c.duration_s,
        "environment": c.environment,
        "labels": c.labels or {},
        "status": c.status,
    }


def _header(c: Call) -> dict:
    return {
        "id": c.external_call_id,
        "source": c.source,
        "environment": c.environment,
        "engine": c.engine,
        "carrier": c.carrier,
        "duration_s": c.duration_s,
        "status": c.status,
    }


def _turn(t: Turn) -> dict:
    return {
        "turn_index": t.turn_index,
        "turn_id": t.turn_id,
        "response_latency_ms": t.response_latency_ms,
        "llm_ttft_ms": t.llm_ttft_ms,
        "tts_ttfb_ms": t.tts_ttfb_ms,
        "cut_reason": t.cut_reason,
    }


def _metric(m: Metric) -> dict:
    return {
        "name": m.name,
        "value": m.value_num if m.value_num is not None else m.value_text,
        "samples": m.samples,
        "available": m.available,
        "reason": m.reason,
    }
