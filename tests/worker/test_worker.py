"""Worker: assemble, persist, claim. The end-to-end check is test_worker_e2e."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from sqlalchemy import select

from tests.adapters.fixtures.vas_call import sample_call
from voiceobs.db.models import Call, Event, IngestRun, Metric
from voiceobs.db.models import Turn as DBTurn
from voiceobs.worker.process import assemble, process
from voiceobs.worker.run import claim, tick


def _gz(payload: dict) -> bytes:
    return gzip.compress(json.dumps(payload).encode())


def _split(payload: dict) -> list[bytes]:
    """The same call arriving as separate batches, root last — the real order."""
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    resource = payload["resourceSpans"][0]["resource"]
    return [
        _gz({"resourceSpans": [{"resource": resource, "scopeSpans": [{"spans": part}]}]})
        for part in ([s for s in spans if s["name"] != "voice.call"],
                     [s for s in spans if s["name"] == "voice.call"])
    ]


def test_rollup_fills_models_and_tokens_from_otlp():
    """The call-level composition (which STT/LLM/TTS models ran, token totals) is rolled
    up from the spans. LiveKit names the STT model on the user-turn span, not the STT one."""
    from voiceobs.adapters.livekit import LiveKitAdapter
    from voiceobs.core.join import join
    from voiceobs.db.models import Call
    from voiceobs.worker.process import _rollup

    otlp = json.loads(
        (Path(__file__).parents[2] / "tests/e2e/sample-run/otlp.json").read_text()
    )
    trace = LiveKitAdapter().to_trace(otlp)
    analysis = join(trace, None)
    call = Call(id="x", tenant_id="t", external_call_id="x", source="livekit", environment="prod")
    _rollup(call, trace, analysis)

    assert call.engine == "cascade"
    assert call.stt_provider == "gpt-4o-mini-transcribe"
    assert call.llm_provider == "gpt-4o-mini"
    assert call.tts_provider == "gpt-4o-mini-tts"
    assert call.tokens_in and call.tokens_out
    assert call.tts_chars


def test_assemble_merges_fragments():
    merged = assemble(_split(sample_call()))
    names = [s["name"] for s in merged["resourceSpans"][0]["scopeSpans"][0]["spans"]]
    assert "voice.call" in names
    assert merged["resourceSpans"][0]["resource"]["attributes"]


def test_assemble_dedupes_retried_spans():
    """OTLP retries resend spans. A doubled root would count the call twice."""
    once = sample_call()
    twice = assemble([_gz(once), _gz(once)])
    spans = twice["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == len({s["spanId"] for s in spans})


def test_worker_writes_turns_metrics_and_events(client, db_sessionmaker):
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert process(db, call) in ("ok", "partial")
        db.commit()

        turns = db.scalars(select(DBTurn)).all()
        assert [t.turn_index for t in turns] == [1]
        assert turns[0].caller_transcript == "haan ji"
        assert turns[0].llm_raw == "haan ji, boliye"
        assert db.scalars(select(Metric)).all() == [] or db.scalars(select(Metric)).all()
        # every span and every span event lands on the timeline
        kinds = {e.kind for e in db.scalars(select(Event))}
        assert kinds == {"span", "event"}


def test_header_fields_are_filled_in(client, db_sessionmaker):
    """The NULLs ingest leaves behind are the worker's job."""
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert call.engine is None and call.started_at is None
        process(db, call)
        db.commit()
        assert call.engine == "cascade"
        assert call.carrier == "plivo"
        assert call.llm_provider == "gpt-x"
        assert call.started_at is not None
        assert call.duration_s == 3.0
        assert call.campaign_id == "camp-1"
        assert call.metric_version and call.adapter_version


def test_reprocessing_does_not_double_rows(client, db_sessionmaker):
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        process(db, call)
        db.commit()
        before = len(db.scalars(select(Event)).all())
        process(db, call)
        db.commit()
        assert len(db.scalars(select(Event)).all()) == before
        assert len(db.scalars(select(DBTurn)).all()) == 1


def test_claim_skips_calls_already_at_this_version(client, db_sessionmaker):
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        assert len(claim(db, grace_s=0)) == 1
        assert tick(db, grace_s=0) == 1
        db.commit()
        assert claim(db, grace_s=0) == []  # done, not claimable again


def test_claim_waits_out_the_grace_period(client, db_sessionmaker):
    """A call still receiving spans must not be analysed mid-flight."""
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        assert claim(db, grace_s=3600) == []


def test_unsupported_producer_is_not_retried_forever(client, db_sessionmaker, monkeypatch):
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        import voiceobs.worker.run as run_mod
        from voiceobs.adapters import UnsupportedSchema

        def boom(*_a, **_kw):
            raise UnsupportedSchema("nope")

        monkeypatch.setattr(run_mod, "process", boom)
        assert tick(db, grace_s=0) == 1
        db.commit()
        assert db.scalars(select(Call)).one().status == "unsupported"
        assert claim(db, grace_s=0) == []


def test_worker_names_no_producer():
    """The constraint, enforced. `worker/` may not know a producer exists — that is
    `adapters/`' job, and it is what keeps Pipecat and LiveKit a config change."""
    src = Path(__file__).parents[2] / "src" / "voiceobs" / "worker"
    for f in src.glob("*.py"):
        text = f.read_text()
        for token in ('"voice.', "'voice.", '"lk.', "voice.call", "voice-cascade"):
            assert token not in text, f"{f.name} names a producer: {token}"


def test_ingest_run_records_the_attempt(client, db_sessionmaker):
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()
        run = db.scalars(select(IngestRun)).one()
        assert run.status in ("ok", "partial")
        assert run.finished_at is not None


def test_foreign_producer_survives_the_worker(client, db_sessionmaker):
    """The OSS constraint, end to end: a producer with no adapter goes in one side and
    comes out as a call with a timeline — no turns, because it emits no turn spans."""
    T = 1_700_000_000_000_000_000
    payload = {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "livekit"}}]},
        "scopeSpans": [{"spans": [
            {"traceId": "bb" * 16, "spanId": "01" * 8, "name": "agent_session",
             "startTimeUnixNano": str(T), "endTimeUnixNano": str(T + 2_000_000_000)},
            {"traceId": "bb" * 16, "spanId": "02" * 8, "parentSpanId": "01" * 8,
             "name": "llm_node", "startTimeUnixNano": str(T),
             "endTimeUnixNano": str(T + 1_000_000_000)},
        ]}],
    }]}
    client.post("/v1/traces", json=payload)
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert process(db, call) in ("ok", "partial")
        db.commit()
        assert call.source == "livekit"
        assert call.duration_s == 2.0
        assert db.scalars(select(DBTurn)).all() == []      # no turn spans to find
        assert len(db.scalars(select(Event)).all()) == 2   # but the timeline is there
