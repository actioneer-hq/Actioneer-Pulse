"""The wire format producers actually use.

`OTLPSpanExporter` has no JSON mode — every real batch is protobuf. These build one
with the OTel SDK itself rather than hand-rolling bytes, because the bug this guards
is a shape mismatch, and a hand-rolled fixture would encode my assumptions twice."""

from __future__ import annotations

import gzip
import json

import pytest
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from sqlalchemy import select

from voiceobs.core.join import join
from voiceobs.db.models import Call, RawFragment
from voiceobs.frameworks import adapter_for

PROTOBUF = {"content-type": "application/x-protobuf"}


class _Capture(SpanExporter):
    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS


@pytest.fixture
def otlp_body() -> bytes:
    """One serialized OTLP/protobuf batch: a call, a turn, and two turn children."""
    cap = _Capture()
    provider = TracerProvider(resource=Resource.create({
        "service.name": "voice-cascade",
        "deployment.environment": "prod",
        "voice.schema_version": 1,
    }))
    provider.add_span_processor(SimpleSpanProcessor(cap))
    tracer = provider.get_tracer("voice")

    call_attrs = {"voice.call_id": "call-pb-1", "voice.tenant_id": "spektra"}
    turn_attrs = {"voice.turn_id": "call-pb-1:1", "voice.turn.index": 1}
    with tracer.start_as_current_span("voice.call", attributes=call_attrs):  # noqa: SIM117
        with tracer.start_as_current_span("voice.turn", attributes=turn_attrs) as turn:
            turn.add_event("turn.committed", attributes={"voice.turn_id": "call-pb-1:1"})
            with tracer.start_as_current_span("transcript", attributes={
                "voice.turn_id": "call-pb-1:1", "voice.content.text": "haan ji",
            }):
                pass
            with tracer.start_as_current_span("llm.generate", attributes={
                "voice.turn_id": "call-pb-1:1", "voice.content.text": "boliye",
            }) as llm:
                llm.add_event("llm.first_token")
    return encode_spans(cap.spans).SerializeToString()


def _reassemble(db) -> dict:
    """What a worker does: one call's fragments back into one payload."""
    spans: list[dict] = []
    resource: dict = {}
    for frag in db.scalars(select(RawFragment).order_by(RawFragment.seq)):
        for rs in json.loads(gzip.decompress(frag.payload_gz))["resourceSpans"]:
            resource = resource or rs["resource"]
            for scope in rs["scopeSpans"]:
                spans += scope["spans"]
    return {"resourceSpans": [{"resource": resource, "scopeSpans": [{"spans": spans}]}]}


def test_protobuf_batch_is_ingested(client, db_sessionmaker, otlp_body):
    assert client.post("/v1/traces", content=otlp_body, headers=PROTOBUF).status_code == 200
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert call.external_call_id == "call-pb-1"
        assert call.tenant_id == "spektra"
        assert call.spans_complete is True
        # hex, not the base64 the protobuf JSON mapping hands back
        assert len(call.trace_id) == 32
        int(call.trace_id, 16)


def test_protobuf_survives_the_round_trip_to_turns(client, db_sessionmaker, otlp_body):
    """Ids decoded wrong still ingest fine and only break here, silently — so assert
    the parent chain, not just that a call row appeared."""
    client.post("/v1/traces", content=otlp_body, headers=PROTOBUF)
    with db_sessionmaker() as db:
        payload = _reassemble(db)

    trace = adapter_for(payload).to_trace(payload)
    by_name = {s.name: s for s in trace.spans}
    assert by_name["voice.call"].parent_span_id is None
    assert by_name["voice.turn"].parent_span_id == by_name["voice.call"].span_id
    assert by_name["transcript"].parent_span_id == by_name["voice.turn"].span_id

    turn = join(trace, None).turns[0]
    assert turn.turn_index == 1
    assert turn.transcript == "haan ji"
    assert turn.llm_raw == "boliye"


def test_gzipped_protobuf_is_ingested(client, login_as, otlp_body):
    r = client.post(
        "/v1/traces",
        content=gzip.compress(otlp_body),
        headers={**PROTOBUF, "content-encoding": "gzip"},
    )
    assert r.status_code == 200
    login_as("spektra")  # the call's org (voice.tenant_id)
    assert client.get("/v1/calls/call-pb-1").status_code == 200


def test_unreadable_body_is_400_not_500(client):
    r = client.post("/v1/traces", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
