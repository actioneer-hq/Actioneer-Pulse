"""VAS adapter — dialect -> Trace, attribute classing, end-to-end into join()."""

from __future__ import annotations

import pytest

from tests.adapters.fixtures.vas_call import sample_call
from voiceobs.adapters import UnsupportedSchema, adapter_for
from voiceobs.adapters.vas import VASAdapter
from voiceobs.core import join
from voiceobs.core.model import Stage


def _trace():
    return VASAdapter().to_trace(sample_call())


def test_matches_only_voice_cascade():
    a = VASAdapter()
    assert a.matches(sample_call()) is True
    assert a.matches(sample_call(service_name="pipecat")) is False


def test_registry_routes_to_vas():
    assert adapter_for(sample_call()).name == "vas"
    assert adapter_for(sample_call(service_name="livekit")) is None


def test_schema_below_1_rejected():
    with pytest.raises(UnsupportedSchema):
        VASAdapter().to_trace(sample_call(schema_version=0))


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


def test_content_routed_and_pii_dropped():
    stt = next(s for s in _trace().spans if s.name == "stt.finalize")
    assert stt.content["transcript"] == "haan ji"
    # neither the content attr nor the leaked prompt survive in shape attrs
    assert "voice.content.transcript" not in stt.attrs
    assert "gen_ai.prompt" not in stt.attrs
    assert stt.attrs["voice.stt_confidence"] == 0.67


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
