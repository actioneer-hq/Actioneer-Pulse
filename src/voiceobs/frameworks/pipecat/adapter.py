"""Pipecat dialect. Span/attr names per Pipecat's OpenTelemetry docs.

Pipecat nests one exchange cleanly: a `conversation` root, `turn` spans under it, and each turn's
`stt`/`llm`/`tts` spans as children of that turn. So — unlike LiveKit — there is no sibling-turn to
re-stitch and no JSON-blob metrics to expand: the generic base's `_propagate_turn_ids` already attaches
each service span to its turn. This adapter is therefore just the two dicts (stage map + a few aliases)
plus the content attrs.

Pipecat already emits OTel GenAI names (`gen_ai.usage.*`) and `metrics.ttfb`, which are Pulse's
canonical names too — those pass straight through; only its turn/stt/tts-specific keys need aliasing."""

from __future__ import annotations

from typing import ClassVar

from voiceobs.core.model import Stage
from voiceobs.frameworks.generic import OTLPAdapter
from voiceobs.frameworks.otlp import iter_spans


class PipecatAdapter(OTLPAdapter):
    name = "pipecat"
    version = 1

    stages: ClassVar[dict[str, Stage]] = {
        "conversation": Stage.CALL,
        "turn": Stage.TURN,
        "stt": Stage.STT,
        "llm": Stage.LLM,
        # multimodal (single-model) variants — still LLM work
        "llm_setup": Stage.LLM,
        "llm_response": Stage.LLM,
        "llm_tool_call": Stage.TOOL,
        "llm_tool_result": Stage.TOOL,
        "tts": Stage.TTS,
    }

    attr_aliases: ClassVar[dict[str, str]] = {
        "turn.number": "turn.index",
        "turn.was_interrupted": "turn.interrupted",
        "language": "stt.language",
        "metrics.character_count": "tts.chars",
        # Pipecat splits cached prompt tokens under cache_read; Pulse canonical is cached_tokens.
        "gen_ai.usage.cache_read.input_tokens": "gen_ai.usage.cached_tokens",
        # already canonical, pass through unrenamed: gen_ai.request.model,
        # gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, and metrics.ttfb on TTS.
    }

    # Pipecat carries conversation text as plain attributes (transcript on stt, text on tts),
    # not under voice.content.* — route them to Span.content like LiveKit does.
    content_attrs: ClassVar[dict[str, str]] = {
        "transcript": "transcript",
        "text": "llm_spoken",
    }

    def derive(self, attrs: dict, stage: Stage) -> dict:
        """Pipecat names every service's first-response latency `metrics.ttfb`. On the LLM span that
        value IS time-to-first-token, so promote it to `metrics.ttft` (Pulse keeps TTFT and TTFB
        distinct). On TTS it already means TTFB and passes through unchanged."""
        if stage is Stage.LLM and "metrics.ttfb" in attrs and "metrics.ttft" not in attrs:
            attrs["metrics.ttft"] = attrs.pop("metrics.ttfb")
        return attrs

    def matches(self, payload: dict) -> bool:
        return any(s.get("name") == "conversation" for _, s in iter_spans(payload))
