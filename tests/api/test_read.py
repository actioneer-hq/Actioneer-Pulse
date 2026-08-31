"""Read endpoint tests — list, consolidated detail, metric-defs."""

from __future__ import annotations

import sys

from sqlalchemy import select

from tests.adapters.fixtures.vas_call import sample_call
from tests.fixtures.synth import SynthCall
from voiceobs.db.models import Call
from voiceobs.worker.process import process


def _wav() -> bytes:
    return SynthCall(duration_s=6.0,
                     speech=[("caller", 1.0, 2.0, 0.8), ("agent", 2.5, 4.0, 0.8)]).build()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_and_filter(client):
    client.post("/v1/traces", json=sample_call())
    assert len(client.get("/v1/calls").json()["items"]) == 1
    assert len(client.get("/v1/calls?status=awaiting_media").json()["items"]) == 1
    assert client.get("/v1/calls?status=ingested").json()["items"] == []


def test_detail_is_one_consolidated_payload(client):
    client.post("/v1/traces", json=sample_call())
    d = client.get("/v1/calls/c1").json()
    assert d["call"]["id"] == "c1"
    # everything the viewer needs, one round trip
    for key in ("turns", "metrics", "trust", "spans", "peaks", "audio", "versions"):
        assert key in d
    assert d["audio"] is None  # no WAV registered yet


def test_spans_endpoint_is_gone(client):
    client.post("/v1/traces", json=sample_call())
    assert client.get("/v1/calls/c1/spans").status_code == 404


def test_full_analysis_after_worker(client, db_sessionmaker, monkeypatch):
    monkeypatch.setattr(
        sys.modules["voiceobs.worker.process"], "fetch_bytes", lambda uri: _wav()
    )
    monkeypatch.setattr("voiceobs.api.read.presign", lambda uri, **kw: "https://signed/x.wav")
    client.post("/v1/traces", json=sample_call())
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
    assert d["audio"]["url"] == "https://signed/x.wav"
    assert d["audio"]["sample_rate"] == 8000
    assert d["trust"]["capture_coverage"]  # pulled from the metric


def test_detail_404(client):
    assert client.get("/v1/calls/nope").status_code == 404


def test_metric_defs_cover_emitted_metrics(client):
    names = {d["name"] for d in client.get("/v1/metric-defs").json()}
    assert {"capture_coverage", "llm_ttft_ms", "talk_ratio_caller", "talk_ratio_agent",
            "turn_count_agent", "llm_ttft_reported_ms"} <= names


def test_ui_is_served_when_built(client):
    """404 in a source checkout, the app when `ui/` has been built. Either is fine;
    a 500 would mean the mount shadowed the API routes."""
    assert client.get("/").status_code in (200, 404)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/v1/calls").status_code == 200
