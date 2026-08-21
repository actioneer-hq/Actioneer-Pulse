"""Ingest endpoint tests — traces sharding/gates, artifacts, prompts, erasure."""

from __future__ import annotations

from tests.adapters.fixtures.vas_call import sample_call


def _artifact(**kw) -> dict:
    body = {
        "kind": "audio", "uri": "gs://b/k", "sha256": "s1", "bytes": 100,
        "content_type": "audio/wav", "channels": 2, "sample_rate": 8000,
        "channel_map": {0: "caller", 1: "agent"}, "t0_offset_s": -0.4,
    }
    body.update(kw)
    return body


def test_traces_creates_call_and_sets_spans_complete(client):
    r = client.post("/v1/traces", json=sample_call())
    assert r.status_code == 200
    assert r.json() == {"partialSuccess": {}}

    call = client.get("/v1/calls/c1").json()["call"]
    assert call["id"] == "c1"
    detail = client.get("/v1/calls/c1").json()
    assert detail["trust"]["spans_complete"] is True
    assert detail["trust"]["media_ready"] is False


def test_traces_idempotent_no_duplicate_call(client):
    client.post("/v1/traces", json=sample_call())
    client.post("/v1/traces", json=sample_call())
    items = client.get("/v1/calls").json()["items"]
    assert [i["id"] for i in items].count("c1") == 1


def test_artifact_sets_media_ready_and_flips_status(client):
    client.post("/v1/traces", json=sample_call())
    r = client.post("/v1/calls/c1/artifacts", json=_artifact())
    assert r.status_code == 200
    assert r.json()["media_ready"] is True
    # spans_complete + media_ready -> ingested
    assert client.get("/v1/calls/c1").json()["call"]["status"] == "ingested"


def test_artifact_idempotent(client):
    client.post("/v1/traces", json=sample_call())
    client.post("/v1/calls/c1/artifacts", json=_artifact())
    r = client.post("/v1/calls/c1/artifacts", json=_artifact())
    assert r.json()["status"] == "exists"


def test_prompt_201_then_200(client):
    body = {"template_sha256": "a" * 64, "text": "SYSTEM"}
    assert client.post("/v1/prompts", json=body).status_code == 201
    assert client.post("/v1/prompts", json=body).status_code == 200


def test_delete_guarded(client):
    client.post("/v1/traces", json=sample_call())
    # missing header/env -> 403
    assert client.delete("/v1/calls/c1").status_code == 403


def test_delete_erases_and_tombstones(client, monkeypatch):
    monkeypatch.setenv("VOICEOBS_ALLOW_DELETE", "1")
    client.post("/v1/traces", json=sample_call())
    r = client.delete("/v1/calls/c1", headers={"X-Voiceobs-Confirm": "c1"})
    assert r.status_code == 200
    # call gone
    assert client.get("/v1/calls/c1").status_code == 404
    # re-POST after erasure is dropped (tombstoned)
    client.post("/v1/traces", json=sample_call())
    assert client.get("/v1/calls/c1").status_code == 404


def test_unattributed_spans_do_not_crash(client):
    payload = sample_call()
    # strip call_id from every span -> all unattributed
    for rs in payload["resourceSpans"]:
        for scope in rs["scopeSpans"]:
            for span in scope["spans"]:
                span["attributes"] = [
                    a for a in span["attributes"] if a["key"] != "voice.call_id"
                ]
    assert client.post("/v1/traces", json=payload).status_code == 200
    assert client.get("/v1/calls").json()["items"] == []
