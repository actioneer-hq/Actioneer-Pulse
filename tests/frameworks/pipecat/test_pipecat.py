"""Pipecat adapter — signature match, stage mapping, attr aliases, content, turn grouping.

Span/attr names follow Pipecat's OpenTelemetry docs: a `conversation` root, `turn` spans, and
`stt`/`llm`/`tts` children under each turn."""

from __future__ import annotations

from tests.fixtures.otlp_build import payload, span

from voiceobs.core import join
from voiceobs.core.model import Stage
from voiceobs.frameworks import adapter_for
from voiceobs.frameworks.pipecat.adapter import PipecatAdapter


def _call() -> dict:
    return payload([
        span("conv", None, "conversation", 0, 3000, {"conversation.id": "c-1"}),
        span("t1", "conv", "turn", 500, 2400,
             {"turn.number": 1, "turn.was_interrupted": False, "turn.duration_seconds": 1.9}),
        span("s-stt", "t1", "stt", 500, 1000,
             {"gen_ai.request.model": "nova-2", "transcript": "hello there",
              "language": "en", "is_final": True, "metrics.ttfb": 0.12}),
        span("s-llm", "t1", "llm", 1100, 1900,
             {"gen_ai.request.model": "gpt-4o", "gen_ai.usage.input_tokens": 50,
              "gen_ai.usage.output_tokens": 20, "metrics.ttfb": 0.30}),
        span("s-tts", "t1", "tts", 1500, 2300,
             {"gen_ai.request.model": "sonic", "voice_id": "v1", "text": "hi, how can i help?",
              "metrics.character_count": 18, "metrics.ttfb": 0.20}),
    ], service_name="pipecat")


def test_registry_routes_to_pipecat():
    assert adapter_for(_call()).name == "pipecat"


def test_stage_mapping():
    by = {s.name: s for s in PipecatAdapter().to_trace(_call()).spans}
    assert by["conversation"].stage is Stage.CALL
    assert by["turn"].stage is Stage.TURN
    assert by["stt"].stage is Stage.STT
    assert by["llm"].stage is Stage.LLM
    assert by["tts"].stage is Stage.TTS


def test_attr_aliases_and_content():
    by = {s.name: s for s in PipecatAdapter().to_trace(_call()).spans}
    assert by["turn"].attrs["turn.index"] == 1              # turn.number -> turn.index
    assert by["turn"].attrs["turn.interrupted"] is False    # turn.was_interrupted -> turn.interrupted
    assert by["stt"].attrs["stt.language"] == "en"          # language -> stt.language
    assert by["stt"].content["transcript"] == "hello there"
    assert by["tts"].attrs["tts.chars"] == 18               # metrics.character_count -> tts.chars
    assert by["tts"].content["llm_spoken"] == "hi, how can i help?"
    # already-canonical names pass straight through
    assert by["llm"].attrs["gen_ai.usage.output_tokens"] == 20
    assert by["stt"].attrs["metrics.ttfb"] == 0.12


def test_turn_grouping_attaches_children():
    """stt/llm/tts nest under `turn`; the base propagates the turn id onto each child."""
    by = {s.name: s for s in PipecatAdapter().to_trace(_call()).spans}
    assert by["turn"].turn_id == "t1"
    assert by["stt"].turn_id == "t1"
    assert by["llm"].turn_id == "t1"
    assert by["tts"].turn_id == "t1"


def test_join_runs_and_maps_tokens():
    analysis = join(PipecatAdapter().to_trace(_call()), None)
    assert len(analysis.turns) == 1
