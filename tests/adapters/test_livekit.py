"""LiveKit adapter — signature match, stage mapping, turn grouping."""

from __future__ import annotations

from tests.adapters.fixtures.otlp_build import payload, span
from voiceobs.adapters import adapter_for
from voiceobs.adapters.livekit import LiveKitAdapter
from voiceobs.core import join
from voiceobs.core.model import Stage


def _call() -> dict:
    return payload([
        span("sess", None, "agent_session", 0, 3000),
        span("t1", "sess", "user_turn", 900, 2200,
             {"turn.id": "lk:1", "turn.index": 1, "lk.interrupted": True}),
        span("s-eou", "t1", "eou_detection", 600, 1000, {"turn.id": "lk:1"}),
        span("s-llm", "t1", "llm_request", 1100, 1900,
             {"turn.id": "lk:1", "gen_ai.usage.output_tokens": 20}),
        span("s-tts", "t1", "tts_node", 1500, 2200, {"turn.id": "lk:1"}),
        span("s-play", "t1", "agent_speaking", 1700, 2400, {"turn.id": "lk:1"}),
    ], service_name="voice-assistant")


def test_registry_routes_to_livekit():
    assert adapter_for(_call()).name == "livekit"


def test_stage_mapping():
    by = {s.name: s for s in LiveKitAdapter().to_trace(_call()).spans}
    assert by["agent_session"].stage is Stage.CALL
    assert by["eou_detection"].stage is Stage.STT
    assert by["llm_request"].stage is Stage.LLM
    assert by["tts_node"].stage is Stage.TTS
    assert by["agent_speaking"].stage is Stage.PLAYOUT


def test_join_runs_and_maps_tokens():
    analysis = join(LiveKitAdapter().to_trace(_call()), None)
    assert len(analysis.turns) == 1
    assert analysis.turns[0].tokens_out == 20
    assert analysis.turns[0].interrupted is True
