"""Cascade adapter: stage map, call identity, and a waterfall Pulse can compute."""

from __future__ import annotations

from tests.fixtures.otlp_build import MS, T0, payload, span

from voiceobs.core import join
from voiceobs.core.model import Stage
from voiceobs.frameworks import adapter_for
from voiceobs.frameworks.cascade.adapter import CascadeAdapter


def _call() -> dict:
    return payload([
        span("root", None, "voice.call", 0, 4000, {
            "voice.call_id": "call-9",
            "voice.engine": "cascade",
            "voice.carrier": "plivo",
            "voice.campaign_id": "camp-9",
            "voice.template_sha256": "abc",
            "voice.stt_provider": "sarvam",
            "voice.llm_provider": "sarvam",
            "voice.tts_provider": "sarvam",
            "voice.voice": "shubh",
        }),
        span("t1", "root", "voice.turn", 1000, 2800, {
            "voice.turn_id": "t1",
            "voice.turn.trigger": "endpoint",
            "voice.turn.index": 1,
        }),
        span("sp", "t1", "caller.speech", 800, 1000, {"voice.turn_id": "t1"}),
        span("stt", "t1", "transcript", 1200, 1400, {
            "voice.turn_id": "t1",
            "voice.content.transcript": "hello",
            "voice.stt_language": "hi-IN",
            "gen_ai.request.model": "saaras",
        }),
        _event(span("llm", "t1", "llm.generate", 1400, 2000, {
            "voice.turn_id": "t1",
            "gen_ai.request.model": "sarvam-105b",
            "gen_ai.usage.input_tokens": 10,
            "gen_ai.usage.output_tokens": 4,
            "gen_ai.usage.cached_tokens": 2,
        }), "llm.first_token", 1600),
        _event(span("tts", "t1", "tts.synthesize", 1700, 2600, {
            "voice.turn_id": "t1",
            "gen_ai.request.model": "bulbul-v3",
            "voice.tts.chars": 5,
            "voice.content.llm_spoken": "hello",
        }), "tts.first_audio", 1900),
        span("play", "t1", "agent.playout", 1700, 2600, {"voice.turn_id": "t1"}),
        span("mystery", "t1", "vendor.extra", 1800, 1900, {"voice.turn_id": "t1"}),
    ], service_name="voice-cascade")


def _event(node: dict, name: str, at_ms: int) -> dict:
    node = dict(node)
    node["events"] = [{
        "name": name,
        "timeUnixNano": str(T0 + int(at_ms * MS)),
        "attributes": [],
    }]
    return node


def test_registry_routes_cascade_and_leaves_pipecat():
    assert adapter_for(_call()).name == "cascade"
    other = payload([span("c", None, "conversation", 0, 10)], service_name="pipecat")
    assert adapter_for(other).name == "pipecat"


def test_unknown_span_stays_unknown():
    by = {s.name: s for s in CascadeAdapter().to_trace(_call()).spans}
    assert by["vendor.extra"].stage is Stage.UNKNOWN
    assert by["caller.speech"].stage is Stage.SPEECH
    assert by["llm.generate"].stage is Stage.LLM


def test_header_uses_producer_call_id_and_campaign():
    header = CascadeAdapter().to_trace(_call()).header
    assert header.call_id == "call-9"
    assert header.engine == "cascade"
    assert header.carrier == "plivo"
    assert header.template_sha256 == "abc"
    assert header.labels["campaign_id"] == "camp-9"
    assert header.voice == "shubh"


def test_join_waterfall():
    turn = join(CascadeAdapter().to_trace(_call()), None).turns[0]
    assert turn.transcript == "hello"
    assert turn.language == "hi-IN"
    assert turn.tokens_in == 10
    assert turn.tokens_cached == 2
    assert turn.tts_chars == 5
    assert turn.llm_spoken == "hello"
    # speech ends at 1.0s, transcript opens at 1.2s
    assert turn.endpointing_ms == 200.0
    assert turn.stt_lag_ms == 200.0
    assert turn.llm_ttft_ms == 200.0
    assert turn.tts_ttfb_ms == 200.0
    # caller stop 1.0s -> first audio 1.9s
    assert turn.response_latency_ms == 900.0
