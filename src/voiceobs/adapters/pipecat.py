"""Pipecat dialect. Names only; OTLPAdapter does the rest.

Span/attr names from Pipecat's OpenTelemetry docs. service.name is user-chosen, so
we match on a signature span (`conversation`) rather than the resource name.

Best-effort until a real Pipecat trace validates it: stage labels, turn grouping and
token usage map cleanly; TTFT/TTFB arrive as span attributes (metrics.ttfb) rather
than the first-token/first-audio events join() reads, so those segments may be None
until a join-side bridge lands."""

from __future__ import annotations

from typing import ClassVar

from voiceobs.adapters.generic import OTLPAdapter
from voiceobs.adapters.otlp import iter_spans
from voiceobs.core.model import Stage


class PipecatAdapter(OTLPAdapter):
    name = "pipecat"
    version = 1

    stages: ClassVar[dict[str, Stage]] = {
        "conversation": Stage.CALL,
        "turn": Stage.TURN,
        "stt": Stage.STT,
        "llm": Stage.LLM,
        "tts": Stage.TTS,
        "llm_tool_call": Stage.TOOL,
    }

    attr_aliases: ClassVar[dict[str, str]] = {
        "turn.number": "turn.index",
        "turn.type": "turn.trigger",
        "turn.was_interrupted": "turn.interrupted",
        "gen_ai.request.model": "gen_ai.request.model",
        "metrics.ttfb": "metrics.ttfb",
        "tts.character_count": "tts.chars",
        "voice_id": "tts.voice",
    }

    def matches(self, payload: dict) -> bool:
        return any(s.get("name") == "conversation" for _, s in iter_spans(payload))
