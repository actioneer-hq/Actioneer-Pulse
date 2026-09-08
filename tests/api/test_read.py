"""Read endpoint tests — list, consolidated detail, metric-defs."""

from __future__ import annotations

import sys

from sqlalchemy import select

from tests.fixtures.livekit_call import sample_call
from tests.fixtures.synth import SynthCall
from voiceobs.db.models import Call
from voiceobs.worker.process import process


def _wav() -> bytes:
    return SynthCall(duration_s=6.0,
                     speech=[("caller", 1.0, 2.0, 0.8), ("agent", 2.5, 4.0, 0.8)]).build()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_and_filter(client, login_as, drain):
    client.post("/v1/traces", json=sample_call())
    drain()
    login_as("vastu-hfc")  # sample_call's org
    assert len(client.get("/v1/calls").json()["items"]) == 1
    assert len(client.get("/v1/calls?status=awaiting_media").json()["items"]) == 1
    assert client.get("/v1/calls?status=ingested").json()["items"] == []
    assert client.get("/v1/calls?q=c1").json()["items"][0]["id"] == "c1"
    assert client.get("/v1/calls?q=nomatch").json()["items"] == []


def test_list_carries_turn_stats(client, login_as, db_sessionmaker, monkeypatch, drain):
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes", lambda uri, creds=None: _wav()
    )
    client.post("/v1/traces", json=sample_call())
    drain()
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()
    login_as("vastu-hfc")
    item = client.get("/v1/calls").json()["items"][0]
    for key in ("turns", "barge_ins", "p50_v2v_ms", "media_ready", "analysed"):
        assert key in item
    assert item["turns"] >= 1
    assert item["analysed"] is True


def test_detail_is_one_consolidated_payload(client, login_as, drain):
    client.post("/v1/traces", json=sample_call())
    drain()
    login_as("vastu-hfc")
    d = client.get("/v1/calls/c1").json()
    assert d["call"]["id"] == "c1"
    # everything the viewer needs, one round trip
    for key in ("turns", "metrics", "trust", "spans", "peaks", "audio", "versions"):
        assert key in d
    assert d["audio"] is None  # no WAV registered yet


def test_spans_endpoint_is_gone(client):
    client.post("/v1/traces", json=sample_call())
    assert client.get("/v1/calls/c1/spans").status_code == 404


def test_full_analysis_after_worker(client, login_as, db_sessionmaker, monkeypatch, drain):
    monkeypatch.setenv("VOICEOBS_AUDIO_ANALYSIS", "1")  # audio overlay is off by default
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes", lambda uri, creds=None: _wav()
    )
    monkeypatch.setattr("voiceobs.api.read.fetch_bytes", lambda uri, creds=None: _wav())
    client.post("/v1/traces", json=sample_call())
    drain()
    login_as("vastu-hfc")
    client.post("/v1/calls/c1/artifacts", json={
        "kind": "audio", "uri": "s3://b/c1.wav", "channels": 2, "sample_rate": 8000,
        "channel_map": {0: "caller", 1: "agent"}, "t0_offset_s": 0.0,
    })
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()

    d = client.get("/v1/calls/c1").json()
    assert d["spans"]  # the waterfall tree
    assert set(d["peaks"]) == {"caller", "agent"}  # base64 per channel
    # dBFS energy profile, base64 LE float32 per channel + framing to decode it
    assert set(d["energy"]["channels"]) == {"caller", "agent"}
    assert d["energy"]["encoding"] == "f32le"
    assert d["energy"]["frame_ms"] == 20.0
    assert d["energy"]["floor_dbfs"] < 0
    assert d["audio"]["url"] == "/v1/calls/c1/audio"  # same-origin proxy, not a signed S3 URL
    assert d["audio"]["sample_rate"] == 8000
    assert d["trust"]["capture_coverage"]  # pulled from the metric

    # the proxy streams the bytes through the API (RBAC-scoped, no S3 in the browser)
    r = client.get("/v1/calls/c1/audio")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content == _wav()


def test_detail_404(client, login_as):
    login_as("default")
    assert client.get("/v1/calls/nope").status_code == 404


def test_reads_require_auth(client):
    assert client.get("/v1/calls").status_code == 401
    assert client.get("/v1/calls/c1").status_code == 401


def test_metric_defs_cover_emitted_metrics(client):
    names = {d["name"] for d in client.get("/v1/metric-defs").json()}
    assert {"capture_coverage", "llm_ttft_ms", "talk_ratio_caller", "talk_ratio_agent",
            "turn_count_agent", "llm_ttft_reported_ms"} <= names


def test_ui_is_served_when_built(client, login_as):
    """404 in a source checkout, the app when `ui/` has been built. Either is fine;
    a 500 would mean the mount shadowed the API routes."""
    login_as("default")
    assert client.get("/").status_code in (200, 404)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/v1/calls").status_code == 200
