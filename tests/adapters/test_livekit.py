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


def _real_tree() -> dict:
    """LiveKit's actual shape: user_turn (STT) + a sibling agent_turn (LLM/TTS), with
    latency as lk.response.* attrs and tokens on the llm_request sub-span."""
    return payload([
        span("sess", None, "agent_session", 0, 4000),
        span("ut", "sess", "user_turn", 900, 1100,
             {"turn.index": 0, "lk.end_of_turn_delay": 0.4,
              "lk.pii.user_transcript": "hello there"}),
        span("eou", "ut", "eou_detection", 900, 1000, {"lk.transcript_confidence": 0.95}),
        span("at", "sess", "agent_turn", 1100, 3500,             # sibling of user_turn
             {"lk.interrupted": True, "lk.interruption.probability": 0.82,
              "lk.e2e_latency": 2.1, "lk.pii.response.text": "hi, how can I help?"}),
        span("lnode", "at", "llm_node", 1150, 1900, {"lk.response.ttft": 0.9}),
        span("lreq", "lnode", "llm_request", 1150, 1900,
             {"gen_ai.usage.input_tokens": 50, "gen_ai.usage.output_tokens": 34}),
        span("tnode", "at", "tts_node", 2000, 3400, {"lk.response.ttfb": 1.5}),
        span("play", "at", "agent_speaking", 2100, 3400),
    ])


def test_agent_turn_folds_into_the_caller_turn():
    trace = LiveKitAdapter().to_trace(_real_tree())
    analysis = join(trace, None)
    assert len(analysis.turns) == 1                 # one exchange, not two
    t = analysis.turns[0]
    assert t.llm_ttft_reported_ms == 900.0          # lk.response.ttft, from llm_node
    assert t.tts_ttfb_reported_ms == 1500.0         # lk.response.ttfb, from tts_node
    assert t.tokens_out == 34                        # from the llm_request sub-span
    assert t.tts_span_present is True


def test_harvests_livekits_rich_otlp():
    """LiveKit puts interruption, endpointing, confidence, transcript, and its own
    end-to-end latency in OTLP — all on the turn spans, not the stage spans."""
    t = join(LiveKitAdapter().to_trace(_real_tree()), None).turns[0]
    assert t.interrupted is True
    assert t.interruption_probability == 0.82
    assert t.endpointing_ms == 400.0                # lk.end_of_turn_delay, bridged
    assert t.stt_confidence == 0.95                 # lk.transcript_confidence
    assert t.e2e_latency_ms == 2100.0               # lk.e2e_latency (engine's own)
    assert t.transcript == "hello there"            # lk.pii.user_transcript
    assert t.llm_spoken == "hi, how can I help?"    # lk.pii.response.text
    # the waterfall now reads complete from attributes alone (no first-token/audio events)
    assert t.llm_ttft_ms == 900.0
    assert t.tts_ttfb_ms == 1500.0
