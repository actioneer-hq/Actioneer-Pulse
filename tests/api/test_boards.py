"""Boards aggregation — RBAC scoping, buckets/rates/percentiles, and the live SSE snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from voiceobs.db.models import Call, Event, Judgment, Turn

_ids = iter(range(10000))


def _call(db, org, *, status="ingested", cost=1.0, mins_ago=60, agent_id=None,
          latencies=(), disposition="connected", jstatus="ok", violation=None):
    started = datetime.now(UTC) - timedelta(minutes=mins_ago)
    c = Call(tenant_id=org, external_call_id=f"c{next(_ids)}", source="livekit",
             environment="prod", status=status, started_at=started, created_at=started,
             last_activity_at=started, duration_s=30.0, agent_id=agent_id,
             cost_total=cost, cost_llm=cost, cost_stt=0.0, cost_tts=0.0)
    db.add(c)
    db.flush()
    for i, ms in enumerate(latencies):
        db.add(Turn(call_id=c.id, tenant_id=org, turn_index=i, turn_id=f"{c.id}:{i}",
                    trigger="response", interrupted=False, response_latency_ms=ms))
    if disposition is not None:
        db.add(Judgment(call_id=c.id, tenant_id=org, disposition=disposition, status=jstatus,
                        guardrail_violation=violation))
    db.commit()
    return c


def test_summary_volume_cost_and_totals(client, login_as, db_sessionmaker):
    login_as("default")
    with db_sessionmaker() as db:
        _call(db, "default", cost=2.0, latencies=(100, 200, 300))
        _call(db, "default", cost=3.0, latencies=(400,))
    d = client.get("/v1/boards/summary?range=24h").json()
    assert d["range"] == "24h"
    assert sum(d["volume"]) == 2
    assert d["totals"]["calls"] == 2
    assert d["totals"]["cost_total"] == 5.0
    assert d["totals"]["p50_ms"] is not None  # percentiles computed over the 4 turns
    assert len(d["buckets"]) == len(d["volume"])  # x-axis aligns with every series


def test_failure_and_disposition(client, login_as, db_sessionmaker):
    login_as("default")
    with db_sessionmaker() as db:
        _call(db, "default", disposition="connected")
        _call(db, "default", disposition="no_answer")   # counts as failure
        _call(db, "default", status="failed", disposition=None)  # counts as failure
    d = client.get("/v1/boards/summary?range=24h").json()
    assert sum(d["failure"]["failed"]) == 2
    assert sum(d["failure"]["total"]) == 3
    assert d["totals"]["failure_rate"] > 0.6
    assert d["disposition"]["connected"] == 1
    assert d["disposition"]["no_answer"] == 1


def test_guardrail_rate(client, login_as, db_sessionmaker):
    login_as("default")
    with db_sessionmaker() as db:
        _call(db, "default", violation=True)
        _call(db, "default", violation=False)
    d = client.get("/v1/boards/summary?range=24h").json()
    assert sum(d["guardrail"]["violations"]) == 1
    assert sum(d["guardrail"]["judged"]) == 2
    assert d["totals"]["violation_rate"] == 0.5


def test_tool_calls_and_errors(client, login_as, db_sessionmaker):
    login_as("default")
    with db_sessionmaker() as db:
        c = _call(db, "default")
        # three tool spans on the call, one errored
        for i, err in enumerate([None, None, True]):
            db.add(Event(call_id=c.id, tenant_id="default", kind="span", type="tool",
                         name="function_tool", t_offset_s=float(i), error=err))
        db.commit()
    d = client.get("/v1/boards/summary?range=24h").json()
    assert sum(d["tools"]["calls"]) == 3
    assert sum(d["tools"]["errors"]) == 1
    assert d["totals"]["tool_calls"] == 3
    assert d["totals"]["tool_error_rate"] == round(1 / 3, 4)


def test_rbac_scoped_to_org(client, login_as, db_sessionmaker):
    login_as("default")
    with db_sessionmaker() as db:
        _call(db, "default")
        _call(db, "other-org")  # different tenant — must not appear
    d = client.get("/v1/boards/summary?range=24h").json()
    assert d["totals"]["calls"] == 1


def test_requires_auth(client):
    assert client.get("/v1/boards/summary").status_code == 401


def test_stream_first_snapshot(client, login_as, db_sessionmaker):
    # Drive the generator directly — it's an infinite live loop, so we take only the first yield
    # and close it (avoids hanging TestClient on an unbounded SSE stream). `client` fixture points
    # the module session at the test engine, which _stream() uses via its own get_session().
    login_as("default")
    with db_sessionmaker() as db:
        _call(db, "default", cost=1.0, latencies=(150,))
    from voiceobs.api.boards import _stream
    gen = _stream("default", "u-default-owner", None, None, "24h")
    try:
        first = next(gen)
    finally:
        gen.close()
    event = json.loads(first[5:])
    assert event["type"] == "snapshot"
    assert event["data"]["totals"]["calls"] == 1
