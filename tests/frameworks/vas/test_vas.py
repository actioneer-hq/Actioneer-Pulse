"""VAS adapter — dialect -> Trace, attribute classing, end-to-end into join()."""

from __future__ import annotations

import pytest

from tests.fixtures.vas_call import sample_call
from voiceobs.core import join
from voiceobs.core.model import Stage
from voiceobs.frameworks import UnsupportedSchema, adapter_for
from voiceobs.frameworks.vas.adapter import VASAdapter


def _trace():
    return VASAdapter().to_trace(sample_call())


def test_matches_only_voice_cascade():
    a = VASAdapter()
    assert a.matches(sample_call()) is True
    assert a.matches(sample_call(service_name="pipecat")) is False


def test_registry_routes_to_vas():
    assert adapter_for(sample_call()).name == "vas"
    # a producer VO has no adapter for still resolves — to the generic one, not None
    assert adapter_for(sample_call(service_name="livekit")).name == "otlp"


def test_missing_schema_version_degrades_not_rejects():
    """A producer that hasn't started stamping schema_version still parses — rejecting
    on a field we invented is how VO became VAS-only."""
    trace = VASAdapter().to_trace(sample_call(schema_version=0))
    assert trace.header.call_id == "c1"


def test_future_schema_rejected():
    with pytest.raises(UnsupportedSchema):
        VASAdapter().to_trace(sample_call(schema_version=99))


def test_stage_mapping_and_turn_ids():
    trace = _trace()
    by_name = {s.name: s for s in trace.spans}
    assert by_name["voice.call"].stage is Stage.CALL
    assert by_name["stt.finalize"].stage is Stage.STT
    assert by_name["llm.generate"].stage is Stage.LLM
    assert by_name["tts.synthesize"].stage is Stage.TTS
    assert by_name["voice.call"].turn_id is None  # root has no turn
    assert by_name["stt.finalize"].turn_id == "c1:1"


def test_times_are_seconds_from_t0():
    trace = _trace()
    root = next(s for s in trace.spans if s.name == "voice.call")
    assert root.t_start == 0.0
    llm = next(s for s in trace.spans if s.name == "llm.generate")
    assert llm.t_start == pytest.approx(1.1)  # 1100ms
    ft = next(e for e in llm.events if e.name == "llm.first_token")
    assert ft.t == pytest.approx(1.4)


def test_content_is_split_out_not_dropped():
    stt = next(s for s in _trace().spans if s.name == "stt.finalize")
    assert stt.content["transcript"] == "haan ji"
    assert "voice.content.transcript" not in stt.attrs  # moved to content, not deleted
    assert stt.attrs["stt.confidence"] == 0.67
    # everything else the producer sent is kept — VO is where you go to see the call
    assert stt.attrs["gen_ai.prompt"] == "SYSTEM PROMPT LEAK"


def test_header_fields():
    h = _trace().header
    assert h.call_id == "c1"
    assert h.engine == "cascade"
    assert h.carrier == "plivo"
    assert h.stt_provider == "sarvam-stt"
    assert h.llm_model is None  # provider string embeds the model
    assert h.template_sha256 == "a" * 64
    assert h.labels == {"tenant_id": "vastu-hfc", "campaign_id": "camp-1"}
    assert h.counters["stt_segments_heard"] == 3


def test_adapter_output_feeds_join():
    analysis = join(_trace(), None)  # spans-only Layer-2 path
    assert len(analysis.turns) == 1
    names = {m.name for m in analysis.metrics}
    assert {"llm_ttft_ms", "tts_ttfb_ms", "truncation_rate"} <= names
    trunc = next(m for m in analysis.metrics if m.name == "truncation_rate")
    assert trunc.value == pytest.approx(0.16)  # 16/100


def test_emitted_span_names_map_to_stages():
    """The worker's real names, not the contract's. vas-contract.md documents
    `stt.finalize`; the running producer emits `transcript`, plus two spans the
    contract never mentions. Both vocabularies must land in the right lane."""
    from tests.fixtures.vas_call import _span

    payload = sample_call()
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    spans.append(_span("tx", "t1", "transcript", 600, 1000,
                       {"turn.id": "c1:1", "voice.content.text": "haan ji"}))
    spans.append(_span("sp", "t1", "caller.speech", 500, 950, {"turn.id": "c1:1"}))
    spans.append(_span("po", "t1", "agent.playout", 1700, 2400,
                       {"turn.id": "c1:1", "voice.content.text": "haan ji",
                        "voice.content.clauses": ["haan", "ji"]}))
    spans.append(_span("zz", "t1", "brand.new.span", 100, 200, {}))

    by_name = {s.name: s for s in VASAdapter().to_trace(payload).spans}
    assert by_name["transcript"].stage is Stage.STT
    assert by_name["caller.speech"].stage is Stage.SPEECH
    assert by_name["agent.playout"].stage is Stage.PLAYOUT
    # an unmapped name is unattributed, never quietly `net` — that is how 481 spans hid
    assert by_name["brand.new.span"].stage is Stage.UNKNOWN


def test_content_keys_normalize_by_stage():
    """VAS labels every content attribute `text`; the span says which text it is."""
    from tests.fixtures.vas_call import _span

    payload = sample_call()
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    spans.append(_span("tx", "t1", "transcript", 600, 1000,
                       {"turn.id": "c1:1", "voice.content.text": "haan ji",
                        "voice.content.clauses": ["haan", "ji"]}))
    by_name = {s.name: s for s in VASAdapter().to_trace(payload).spans}
    assert by_name["transcript"].content["transcript"] == "haan ji"
    # a list survives — Span.content is not text-only
    assert by_name["transcript"].content["clauses"] == ["haan", "ji"]


def test_turn_outcome_becomes_interrupted_flag():
    """`voice.outcome` replaced the contract's two booleans; join() reads the booleans."""
    payload = sample_call()
    for sp in payload["resourceSpans"][0]["scopeSpans"][0]["spans"]:
        if sp["name"] == "voice.turn":
            sp["attributes"].append(
                {"key": "voice.outcome", "value": {"stringValue": "interrupted"}}
            )
    turn = next(s for s in VASAdapter().to_trace(payload).spans if s.name == "voice.turn")
    assert turn.attrs["turn.interrupted"] is True


def test_root_span_events_reach_the_turn():
    """Producers park call-scoped events on the root span, which has no turn_id — the
    event names its own turn instead. Before this, the whole root timeline was invisible."""
    from voiceobs.core.join import _first_event_t
    from voiceobs.core.model import Span, SpanEvent

    root = Span(
        span_id="call", parent_span_id=None, name="voice.call", stage=Stage.CALL,
        t_start=0.0, t_end=3.0, turn_id=None,
        events=[SpanEvent(name="turn.committed", t=1.1, attrs={"turn.id": "c1:1"})],
    )
    assert _first_event_t([root], "turn.committed", "c1:1") == 1.1
    assert _first_event_t([root], "turn.committed", "c1:2") is None
