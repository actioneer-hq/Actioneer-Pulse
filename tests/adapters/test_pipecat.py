"""Pipecat adapter — signature match, stage mapping, turn/token mapping."""

from __future__ import annotations

from tests.adapters.fixtures.otlp_build import payload, span
from voiceobs.adapters import adapter_for
from voiceobs.adapters.pipecat import PipecatAdapter
from voiceobs.core import join
from voiceobs.core.model import Stage


def _call() -> dict:
    return payload([
        span("conv", None, "conversation", 0, 3000),
        span("t1", "conv", "turn", 900, 2200,
             {"turn.id": "p1:1", "turn.number": 1, "turn.was_interrupted": True}),
        span("s-stt", "t1", "stt", 600, 1000, {"turn.id": "p1:1"}),
        span("s-llm", "t1", "llm", 1100, 1900,
             {"turn.id": "p1:1", "gen_ai.usage.output_tokens": 10}),
        span("s-tts", "t1", "tts", 1500, 2200,
             {"turn.id": "p1:1", "tts.character_count": 50, "voice_id": "meera"}),
    ], service_name="my-agent")


def test_registry_routes_to_pipecat():
    assert adapter_for(_call()).name == "pipecat"


def test_stage_mapping():
    by = {s.name: s for s in PipecatAdapter().to_trace(_call()).spans}
    assert by["conversation"].stage is Stage.CALL
    assert by["stt"].stage is Stage.STT
    assert by["llm"].stage is Stage.LLM
    assert by["tts"].stage is Stage.TTS


def test_turn_and_tokens_mapped():
    analysis = join(PipecatAdapter().to_trace(_call()), None)
    assert len(analysis.turns) == 1
    t = analysis.turns[0]
    assert t.turn_index == 1  # turn.number -> turn.index
    assert t.interrupted is True  # turn.was_interrupted -> turn.interrupted
    assert t.tokens_out == 10
    assert t.tts_chars == 50  # tts.character_count -> tts.chars


def test_times_seconds_from_t0():
    llm = next(s for s in PipecatAdapter().to_trace(_call()).spans if s.name == "llm")
    assert llm.t_start == 1.1
