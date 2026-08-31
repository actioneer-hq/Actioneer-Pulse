"""LiveKit dialect. Names only; OTLPAdapter does the rest.

Span/attr names from LiveKit Agents' telemetry (agent_session root, EOUMetrics,
metrics.ttft/ttfb). Matched on the `agent_session` signature span, not service.name.

Same best-effort caveat as Pipecat: LiveKit reports TTFT/TTFB as attributes, not the
events join() reads, so those waterfall segments may be None for now."""

from __future__ import annotations

from typing import ClassVar

from voiceobs.adapters.generic import OTLPAdapter
from voiceobs.adapters.otlp import iter_spans
from voiceobs.core.model import Stage


class LiveKitAdapter(OTLPAdapter):
    name = "livekit"
    version = 1

    stages: ClassVar[dict[str, Stage]] = {
        "agent_session": Stage.CALL,
        "user_turn": Stage.TURN,
        "agent_speaking": Stage.PLAYOUT,
        "eou_detection": Stage.STT,
        "llm_request": Stage.LLM,
        "llm_node": Stage.LLM,
        "tts_node": Stage.TTS,
        "function_tool": Stage.TOOL,
    }

    # Real LiveKit attribute names (DeepWiki telemetry, issue #4639). Latency is
    # reported as attributes, not first-token/first-audio events.
    attr_aliases: ClassVar[dict[str, str]] = {
        "lk.interrupted": "turn.interrupted",
        "llm_node_ttft": "metrics.ttft",
        "tts_node_ttfb": "metrics.ttfb",
        "end_of_turn_delay": "endpointing_ms",
        "transcription_delay": "stt.lag_ms",
        "gen_ai.request.model": "gen_ai.request.model",
    }

    def matches(self, payload: dict) -> bool:
        return any(s.get("name") == "agent_session" for _, s in iter_spans(payload))
