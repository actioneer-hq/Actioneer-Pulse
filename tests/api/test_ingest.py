"""Ingest endpoint tests — traces sharding/gates, artifacts, prompts, erasure."""

from __future__ import annotations

from sqlalchemy import select

from tests.fixtures.vas_call import sample_call


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
    # no call id and no trace id -> nothing to attribute the spans to at all
    for rs in payload["resourceSpans"]:
        for scope in rs["scopeSpans"]:
            for span in scope["spans"]:
                span.pop("traceId", None)
                span["attributes"] = [
                    a for a in span["attributes"] if a["key"] != "voice.call_id"
                ]
    assert client.post("/v1/traces", json=payload).status_code == 200
    assert client.get("/v1/calls").json()["items"] == []


def _with_trace_id(payload: dict, trace_id: str) -> dict:
    for rs in payload["resourceSpans"]:
        for scope in rs["scopeSpans"]:
            for span in scope["spans"]:
                span["traceId"] = trace_id
    return payload


def test_shards_by_trace_id_not_call_id(client):
    """Two calls in one batch sharing no call_id still separate — traceId is the only
    call identifier every OTLP producer has."""
    a = _with_trace_id(sample_call(), "aaaa")
    b = _with_trace_id(sample_call(), "bbbb")
    for rs in b["resourceSpans"]:
        for scope in rs["scopeSpans"]:
            for span in scope["spans"]:
                for attr in span["attributes"]:
                    if attr["key"] == "voice.call_id":
                        attr["value"] = {"stringValue": "c2"}
    merged = {"resourceSpans": a["resourceSpans"] + b["resourceSpans"]}
    client.post("/v1/traces", json=merged)
    assert {i["id"] for i in client.get("/v1/calls").json()["items"]} == {"c1", "c2"}


def test_call_id_falls_back_to_trace_id(client):
    """A producer with no voice.call_id (Pipecat, LiveKit) is still a call, not a
    dropped batch."""
    payload = _with_trace_id(sample_call(), "deadbeef")
    for rs in payload["resourceSpans"]:
        for scope in rs["scopeSpans"]:
            for span in scope["spans"]:
                span["attributes"] = [
                    a for a in span["attributes"] if a["key"] != "voice.call_id"
                ]
    client.post("/v1/traces", json=payload)
    assert [i["id"] for i in client.get("/v1/calls").json()["items"]] == ["deadbeef"]


def test_archived_fragment_keeps_the_resource(client, db_sessionmaker):
    """RawFragment is the replay copy; a blank resource loses service.name, and no
    adapter can ever claim it again."""
    import gzip
    import json

    from voiceobs.db.models import RawFragment
    from voiceobs.frameworks import adapter_for

    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        frag = db.scalars(select(RawFragment)).first()
        replayed = json.loads(gzip.decompress(frag.payload_gz))
    assert replayed["resourceSpans"][0]["resource"]["attributes"]
    assert adapter_for(replayed).name == "vas"


def test_later_batch_without_root_rejoins_the_same_call(client):
    """VAS puts voice.call_id on the root span only. A follow-up batch of children
    must land on the existing call, not mint a second one keyed by traceId."""
    payload = _with_trace_id(sample_call(), "trace-1")
    client.post("/v1/traces", json=payload)
    client.post("/v1/traces", json=_children_only(sample_call(), "trace-1"))
    assert [i["id"] for i in client.get("/v1/calls").json()["items"]] == ["c1"]


def test_children_before_root_produce_one_call(client):
    """The real arrival order: the root span closes last, so its batch lands after
    every child. The call opens under its trace id and is renamed when the root
    arrives — two rows here would split one conversation in half."""
    client.post("/v1/traces", json=_children_only(sample_call(), "trace-2"))
    assert [i["id"] for i in client.get("/v1/calls").json()["items"]] == ["trace-2"]

    client.post("/v1/traces", json=_with_trace_id(sample_call(), "trace-2"))
    items = client.get("/v1/calls").json()["items"]
    assert [i["id"] for i in items] == ["c1"]
    assert client.get("/v1/calls/c1").json()["trust"]["spans_complete"] is True


def _children_only(payload: dict, trace_id: str) -> dict:
    """The batch a producer sends before the call ends: no root, so no call_id."""
    payload = _with_trace_id(payload, trace_id)
    for rs in payload["resourceSpans"]:
        for scope in rs["scopeSpans"]:
            scope["spans"] = [s for s in scope["spans"] if s["name"] != "voice.call"]
            for span in scope["spans"]:
                span["attributes"] = [
                    a for a in span["attributes"] if a["key"] != "voice.call_id"
                ]
    return payload


def _pipecat_batch(trace_id: str, with_root: bool) -> dict:
    """A producer that has never heard of voice-cascade: generic span names, no
    voice.* attributes, no call id. Only traceId and the parent chain."""
    spans = [
        {"traceId": trace_id, "spanId": "s2", "parentSpanId": "s1",
         "name": "stt_service", "startTimeUnixNano": "1700000000000000000",
         "endTimeUnixNano": "1700000001000000000", "attributes": []},
    ]
    if with_root:
        spans.insert(0, {
            "traceId": trace_id, "spanId": "s1", "name": "conversation",
            "startTimeUnixNano": "1700000000000000000",
            "endTimeUnixNano": "1700000005000000000", "attributes": [],
        })
    return {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "pipecat"}},
        ]},
        "scopeSpans": [{"spans": spans}],
    }]}


def test_foreign_producer_is_ingested(client):
    """No voice.call_id, no voice.tenant_id, no `voice.call` span. The call is named
    after its trace, and the parentless span — OTLP's own definition of a root —
    completes it."""
    client.post("/v1/traces", json=_pipecat_batch("pipecat-1", with_root=False))
    assert [i["id"] for i in client.get("/v1/calls").json()["items"]] == ["pipecat-1"]
    assert client.get("/v1/calls/pipecat-1").json()["trust"]["spans_complete"] is False

    client.post("/v1/traces", json=_pipecat_batch("pipecat-1", with_root=True))
    detail = client.get("/v1/calls/pipecat-1").json()
    assert detail["trust"]["spans_complete"] is True
    assert detail["call"]["source"] == "pipecat"


def test_tenant_header_names_a_producer_that_sends_none(client):
    client.post(
        "/v1/traces",
        json=_pipecat_batch("pipecat-2", with_root=True),
        headers={"X-Voiceobs-Tenant": "acme"},
    )
    assert client.get("/v1/calls/pipecat-2").json()["call"]["id"] == "pipecat-2"


def test_span_tenant_beats_the_header(client):
    """A shared collector's header must not override a call that names its own tenant."""
    client.post(
        "/v1/traces", json=sample_call(), headers={"X-Voiceobs-Tenant": "wrong"}
    )
    assert client.get("/v1/calls/c1").status_code == 200
