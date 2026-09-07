"""Boards — aggregated call metrics for the dashboard.

One `build_snapshot()` powers both the REST summary and the live SSE stream. Everything is
RBAC-scoped exactly like read.list_calls (tenant + visible_agent_ids). Time-bucketing is done in
Python (no date_trunc) so SQLite (tests/dev) and Postgres agree — same convention as read._turn_stats.

Live updates: the SSE stream pushes a fresh snapshot only when the scoped data actually changes
(a call is ingested or (re)judged), detected via a cheap per-scope cursor — not a blind timer. A
Postgres LISTEN/NOTIFY signal can later drive sub-second latency; the cursor check is the portable
path that also works on SQLite.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from voiceobs.api.deps import session_dep
from voiceobs.auth import current_membership, visible_agent_ids
from voiceobs.core.audio.metrics import percentile
from voiceobs.db.models import Call, Event, Judgment, Membership, Turn
from voiceobs.db.session import get_session

router = APIRouter(prefix="/v1/boards")

# range -> (window, bucket size). 24h→hourly, 7d→6h, 30d→daily.
_RANGES: dict[str, tuple[timedelta, int]] = {
    "24h": (timedelta(hours=24), 3600),
    "7d": (timedelta(days=7), 6 * 3600),
    "30d": (timedelta(days=30), 24 * 3600),
}
_STREAM_POLL_S = 1.0      # how often the stream re-checks the change cursor
_HEARTBEAT_EVERY = 15     # emit an SSE comment every N idle polls to keep the connection open


def _now() -> datetime:
    return datetime.now(UTC)


def _scope(stmt: Select, db: Session, mem: Membership,
           agent_id: str | None, environment: str | None) -> Select:
    """RBAC + optional filters — the same clauses as read.list_calls. Tenant scope = schema."""
    ids = visible_agent_ids(db, mem)
    if ids is not None:
        stmt = stmt.where(Call.agent_id.in_(ids))
    if agent_id:
        stmt = stmt.where(Call.agent_id == agent_id)
    if environment:
        stmt = stmt.where(Call.environment == environment)
    return stmt


def _call_time(started: datetime | None, created: datetime) -> datetime:
    return started or created


def _bucket_keys(since: datetime, until: datetime, bucket_s: int) -> list[int]:
    start = int(since.timestamp() // bucket_s) * bucket_s
    end = int(until.timestamp())
    return list(range(start, end + bucket_s, bucket_s))


def _key(t: datetime, bucket_s: int) -> int:
    return int(t.timestamp() // bucket_s) * bucket_s


def build_snapshot(
    db: Session, mem: Membership, *, agent_id: str | None = None,
    environment: str | None = None, range_key: str = "7d",
) -> dict:
    """All board series for one scope, over the selected range."""
    window, bucket_s = _RANGES.get(range_key, _RANGES["7d"])
    until = _now()
    since = until - window
    keys = _bucket_keys(since, until, bucket_s)
    idx = {k: i for i, k in enumerate(keys)}
    n = len(keys)
    in_window = func.coalesce(Call.started_at, Call.created_at) >= since

    # --- calls: volume, failure, cost, disposition ---
    call_rows = db.execute(
        _scope(
            select(Call.started_at, Call.created_at, Call.status,
                   Call.cost_total, Call.cost_llm, Call.cost_stt, Call.cost_tts),
            db, mem, agent_id, environment,
        ).where(in_window)
    ).all()

    volume = [0] * n
    failed = [0] * n
    total = [0] * n
    cost = {k: [0.0] * n for k in ("total", "llm", "stt", "tts")}
    for started, created, status, c_total, c_llm, c_stt, c_tts in call_rows:
        k = idx.get(_key(_call_time(started, created), bucket_s))
        if k is None:
            continue
        volume[k] += 1
        total[k] += 1
        if status == "failed":
            failed[k] += 1
        cost["total"][k] += c_total or 0.0
        cost["llm"][k] += c_llm or 0.0
        cost["stt"][k] += c_stt or 0.0
        cost["tts"][k] += c_tts or 0.0

    # --- judgments: failure (disposition), guardrail, disposition mix ---
    j_rows = db.execute(
        _scope(
            select(Call.started_at, Call.created_at, Judgment.disposition,
                   Judgment.status, Judgment.guardrail_violation)
            .join(Judgment, Judgment.call_id == Call.id),
            db, mem, agent_id, environment,
        ).where(in_window)
    ).all()

    gr_viol = [0] * n
    gr_judged = [0] * n
    disposition = {"connected": 0, "no_answer": 0, "unknown": 0, "none": 0}
    for started, created, disp, jstatus, viol in j_rows:
        k = idx.get(_key(_call_time(started, created), bucket_s))
        disposition[disp if disp in disposition else "none"] += 1
        if k is None:
            continue
        # a judged-but-not-connected call counts toward failure too
        if disp is not None and disp != "connected":
            failed[k] += 1
        if viol is not None:
            gr_judged[k] += 1
            if viol:
                gr_viol[k] += 1

    # --- latency: per-bucket p50/p95 over measurable turns ---
    lat_rows = db.execute(
        _scope(
            select(Call.started_at, Call.created_at, Turn.response_latency_ms)
            .join(Turn, Turn.call_id == Call.id)
            .where(Turn.response_latency_ms.isnot(None),
                   Turn.trigger != "opening", Turn.interrupted.isnot(True)),
            db, mem, agent_id, environment,
        ).where(in_window)
    ).all()

    lat_buckets: list[list[float]] = [[] for _ in range(n)]
    for started, created, v2v in lat_rows:
        k = idx.get(_key(_call_time(started, created), bucket_s))
        if k is not None:
            lat_buckets[k].append(v2v)
    p50 = [percentile(b, 50) for b in lat_buckets]
    p95 = [percentile(b, 95) for b in lat_buckets]

    # --- tool calls: count + errors (tool spans persist as Event type="tool") ---
    tool_rows = db.execute(
        _scope(
            select(Call.started_at, Call.created_at, Event.error)
            .join(Event, Event.call_id == Call.id)
            .where(Event.kind == "span", Event.type == "tool"),
            db, mem, agent_id, environment,
        ).where(in_window)
    ).all()
    tool_calls = [0] * n
    tool_err = [0] * n
    for started, created, err in tool_rows:
        k = idx.get(_key(_call_time(started, created), bucket_s))
        if k is None:
            continue
        tool_calls[k] += 1
        if err:
            tool_err[k] += 1
    tool_rate = [round(tool_err[i] / tool_calls[i], 4) if tool_calls[i] else 0.0 for i in range(n)]

    rate = [round(failed[i] / total[i], 4) if total[i] else 0.0 for i in range(n)]
    gr_rate = [round(gr_viol[i] / gr_judged[i], 4) if gr_judged[i] else 0.0 for i in range(n)]
    all_lat = [v for b in lat_buckets for v in b]
    calls_total = sum(volume)

    return {
        "range": range_key,
        "bucket_s": bucket_s,
        "buckets": [datetime.fromtimestamp(k, UTC).isoformat() for k in keys],
        "volume": volume,
        "failure": {"failed": failed, "total": total, "rate": rate},
        "latency": {"p50": p50, "p95": p95},
        "guardrail": {"violations": gr_viol, "judged": gr_judged, "rate": gr_rate},
        "tools": {"calls": tool_calls, "errors": tool_err, "rate": tool_rate},
        "cost": cost,
        "disposition": disposition,
        "totals": {
            "calls": calls_total,
            "failure_rate": round(sum(failed) / calls_total, 4) if calls_total else 0.0,
            "p50_ms": percentile(all_lat, 50),
            "p95_ms": percentile(all_lat, 95),
            "cost_total": round(sum(cost["total"]), 4),
            "violation_rate": round(sum(gr_viol) / sum(gr_judged), 4) if sum(gr_judged) else 0.0,
            "tool_calls": sum(tool_calls),
            "tool_error_rate": round(sum(tool_err) / sum(tool_calls), 4) if sum(tool_calls) else 0.0,
        },
    }


@router.get("/summary")
def summary(
    mem: Membership = Depends(current_membership),
    db: Session = Depends(session_dep),
    agent_id: str | None = None,
    environment: str | None = None,
    range: str = Query("7d"),
) -> dict:
    return build_snapshot(db, mem, agent_id=agent_id, environment=environment, range_key=range)


def _cursor(db: Session, mem: Membership, agent_id: str | None, environment: str | None) -> tuple:
    """A cheap fingerprint of the scoped data — changes when a call is added/updated or judged."""
    count, last_act, last_created = db.execute(
        _scope(select(func.count(Call.id), func.max(Call.last_activity_at),
                      func.max(Call.created_at)), db, mem, agent_id, environment)
    ).one()
    judged = db.scalar(
        _scope(select(func.max(Judgment.judged_at)).select_from(Call)
               .join(Judgment, Judgment.call_id == Call.id), db, mem, agent_id, environment)
    )
    return (count, str(last_act), str(last_created), str(judged))


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _stream(org_id: str, user_id: str, agent_id: str | None,
            environment: str | None, range_key: str) -> Iterator[str]:
    """Emit the initial snapshot, then a fresh one whenever the scope's cursor advances."""
    db = next(get_session())
    try:
        mem = db.scalar(select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == user_id))
        if mem is None:
            yield _sse({"type": "error", "error": "no access to this organization"})
            return
        def snap() -> dict:
            return build_snapshot(db, mem, agent_id=agent_id,
                                  environment=environment, range_key=range_key)

        cur = _cursor(db, mem, agent_id, environment)
        yield _sse({"type": "snapshot", "data": snap()})
        idle = 0
        while True:
            time.sleep(_STREAM_POLL_S)
            db.rollback()  # end the implicit txn so each cursor read sees freshly committed rows
            new = _cursor(db, mem, agent_id, environment)
            if new != cur:
                cur = new
                idle = 0
                yield _sse({"type": "snapshot", "data": snap()})
            else:
                idle += 1
                if idle % _HEARTBEAT_EVERY == 0:
                    yield ": keep-alive\n\n"
    except GeneratorExit:
        return
    finally:
        db.close()


@router.get("/stream")
def stream(
    mem: Membership = Depends(current_membership),
    agent_id: str | None = None,
    environment: str | None = None,
    range: str = Query("7d"),
) -> StreamingResponse:
    """Live board metrics as SSE — pushes a new snapshot on each scope change (call ingested/judged)."""
    return StreamingResponse(
        _stream(mem.org_id, mem.user_id, agent_id, environment, range),
        media_type="text/event-stream",
    )
