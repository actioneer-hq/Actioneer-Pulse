"""The wizard's integration manifest: token-authed registration + the manifest runtime
(discover → decode → map → assemble → analyse) executing it end-to-end."""

from __future__ import annotations

from datetime import UTC, datetime

MANIFEST = {
    "schema": "pulse.integration",
    "version": 1,
    "integration": {"framework": "custom", "language": "python", "use_case": "support"},
    "connections": [],
    "artifacts": [
        {
            "id": "conversation",
            "connection": "store",
            "selector": {"object_path_regex": r"^calls/([^/]+)/conversation\.txt$"},
            "correlation": {"call_id": {"from": "path_capture", "group": 1}},
            "decoder": {"type": "text"},
            "emits": [{"target": "transcript", "mapper": "conv-transcript"}],
        },
        {
            "id": "events",
            "connection": "store",
            "selector": {"object_path_regex": r"^calls/([^/]+)/events\.json$"},
            "correlation": {"call_id": {"from": "path_capture", "group": 1}},
            "decoder": {"type": "json"},
            "emits": [
                {"target": "trace", "mapper": "events-trace"},
                {"target": "call", "mapper": "events-call"},
            ],
        },
    ],
    "mappers": {
        # one dialogue line per text line: "speaker: text", sequence = line index
        "conv-transcript": {
            "language": "jsonata", "input": "text", "output": "transcript",
            "cardinality": "one",
            "expression": (
                '($lines := $filter($split(data.text, "\\n"), function($l) { $trim($l) != "" });'
                ' {"call_id": _pulse.call_id, "turns": [$map($lines,'
                ' function($l, $i) { {"speaker": $substringBefore($l, ": ") = "user" ?'
                ' "caller" : "agent", "text": $substringAfter($l, ": "), "sequence": $i} })]})'
            ),
        },
        "events-trace": {
            "language": "jsonata", "input": "json", "output": "trace",
            "cardinality": "one",
            "expression": (
                '{"call_id": _pulse.call_id, "spans": [{"span_id": _pulse.call_id & "-p",'
                ' "parent_span_id": null, "name": "pipeline", "stage": "call",'
                ' "sequence": 0, "attrs": {}, "content": {},'
                ' "events": [$map(data.events, function($e) { {"name": $e.kind,'
                ' "t": $e.t, "attrs": {}, "content": {"detail": $e.detail}} })]}]}'
            ),
        },
        "events-call": {
            "language": "jsonata", "input": "json", "output": "call",
            "cardinality": "one",
            "expression": '{"call_id": _pulse.call_id, "engine": data.engine}',
        },
    },
    "expected_capabilities": {},
}

CONVERSATION = "user: hello\nagent: hi, am I speaking with Priya?\n"
EVENTS = {
    "engine": "cascade",
    "events": [
        {"t": 0.42, "kind": "stt.final", "detail": "hello"},
        {"t": 2.10, "kind": "tts.first_audio", "detail": "turn 1"},
    ],
}


def _agent_and_token(client, login_as) -> tuple[str, str]:
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Files Bot"}).json()["id"]
    token = client.post(f"/v1/agents/{aid}/ingest-tokens", json={"name": "w"}).json()["token"]
    return aid, token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_manifest_upserts_and_bumps_version(client, login_as):
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/integration-manifest", json=MANIFEST, headers=_auth(token))
    assert r.status_code == 200 and r.json()["version"] == 1
    r2 = client.put("/v1/ingest/integration-manifest", json=MANIFEST, headers=_auth(token))
    assert r2.json()["version"] == 2
    got = client.get("/v1/ingest/integration-manifest", headers=_auth(token)).json()
    assert got["manifest"]["schema"] == "pulse.integration" and got["version"] == 2


def test_register_rejects_wrong_schema(client, login_as):
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/integration-manifest", json={"schema": "nope"},
                   headers=_auth(token))
    assert r.status_code == 422


def test_ingest_method_defaults_and_echoes(client, login_as):
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/integration-manifest", json=MANIFEST, headers=_auth(token))
    assert r.json()["ingest_method"] == "storage_polling"  # default when absent
    got = client.get("/v1/ingest/integration-manifest", headers=_auth(token)).json()
    assert got["ingest_method"] == "storage_polling"


def test_ingest_method_rejects_unknown_value(client, login_as):
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/integration-manifest",
                   json={**MANIFEST, "ingest_method": "carrier_pigeon"}, headers=_auth(token))
    assert r.status_code == 422


def test_non_polling_method_needs_no_artifacts(client, login_as):
    """telemetry_ingest_event routes to OTLP push — it carries no mappers/artifacts."""
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/integration-manifest",
                   json={"schema": "pulse.integration", "ingest_method": "telemetry_ingest_event"},
                   headers=_auth(token))
    assert r.status_code == 200 and r.json()["ingest_method"] == "telemetry_ingest_event"


def test_runtime_executes_manifest_end_to_end(client, login_as, db_sessionmaker, monkeypatch):
    """discover → decode → map → assemble → analyse, against a fake store. The transcript
    becomes untimed STT/TTS spans (sequence order), events derive turns/latency, gates
    self-tick, and Turn rows land for the UI."""
    aid, token = _agent_and_token(client, login_as)
    client.put("/v1/ingest/integration-manifest", json=MANIFEST, headers=_auth(token))

    import json as _json

    from voiceobs.integration import discover_manifest, process_manifest_call, resolve_manifest
    from voiceobs.storage.config import ResolvedStorage

    objects = {
        "s3://b/calls/c-77/conversation.txt": CONVERSATION.encode(),
        "s3://b/calls/c-77/events.json": _json.dumps(EVENTS).encode(),
        "s3://b/calls/ignore.me": b"x",
    }

    class FakeDriver:
        scheme = "s3"

        def list(self, descriptor, creds):
            return [(uri, datetime.now(UTC)) for uri in objects]

    st = ResolvedStorage("s3_compatible", {"bucket": "b"}, {}, FakeDriver())
    monkeypatch.setattr("voiceobs.integration.runtime.fetch_bytes",
                        lambda uri, creds=None: objects[uri])

    with db_sessionmaker() as db:
        manifest, version = resolve_manifest(db, aid)
        found = discover_manifest(st, manifest)
        assert set(found) == {"c-77"} and len(found["c-77"]) == 2

        status = process_manifest_call(db, aid, "c-77", found["c-77"], None, manifest, version)
        db.commit()
        assert status in ("ok", "partial")

    detail = client.get("/v1/calls/c-77").json()
    assert detail["call"]["engine"] == "cascade"
    assert detail["call"]["spans_complete"] is True  # self-ticked gate
    # dialogue landed (untimed transcript spans) and the event clock derived a turn
    assert detail["turns"], "expected derived turns"
    assert detail["turns"][0]["caller_transcript"] == "hello"
    assert detail["turns"][0]["response_latency_ms"] == 1680.0
    assert "turns_derived_from_events" in detail["trust"]["reasons"]
    texts = [sp.get("content_text") for sp in detail["spans"]]
    assert "hi, am I speaking with Priya?" in texts  # agent line rides its TTS span
    # canonical order survives with no clock: caller line (seq 0) before agent line (seq 1)
    assert texts.index("hello") < texts.index("hi, am I speaking with Priya?")
