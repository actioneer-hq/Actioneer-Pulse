"""VAS adapter — the `voice-cascade` dialect. Names only; the machinery is OTLPAdapter.

Span and attribute meanings: docs/vas-telemetry-semantics.md (generated from the
producer's source). Where that document and `vas-contract.md` disagree, the document
is right — the contract drifted, so both vocabularies are carried below."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from voiceobs.adapters.base import UnsupportedSchema
from voiceobs.adapters.generic import OTLPAdapter, _dt
from voiceobs.adapters.otlp import attrs_to_dict, span_end_ns, span_start_ns
from voiceobs.core.model import CallHeader, Stage

log = logging.getLogger(__name__)

SERVICE_NAME = "voice-cascade"
MAX_SCHEMA = 1


class VASAdapter(OTLPAdapter):
    name = "vas"
    version = 1
    service_name = SERVICE_NAME

    # Contract names and emitted names both — they drifted, and renaming spans the
    # producer's own dashboards key off is not VO's call to make.
    stages: ClassVar[dict[str, Stage]] = {
        "voice.call": Stage.CALL,
        "voice.turn": Stage.TURN,
        "stt.finalize": Stage.STT,  # contract
        "transcript": Stage.STT,  # emitted
        "caller.speech": Stage.SPEECH,
        "llm.generate": Stage.LLM,
        "tts.synthesize": Stage.TTS,
        "agent.playout": Stage.PLAYOUT,
        "tool.execute": Stage.TOOL,
        "tool.claim": Stage.TOOL,
        "tool.http": Stage.TOOL,
        "net.connect": Stage.NET,
    }

    attr_aliases: ClassVar[dict[str, str]] = {
        "voice.turn_id": "turn.id",
        "voice.turn.index": "turn.index",
        "voice.turn.trigger": "turn.trigger",
        "voice.interrupted": "turn.interrupted",  # contract
        "voice.abandoned": "turn.abandoned",  # contract
        "voice.stt_language": "stt.language",
        "voice.stt_confidence": "stt.confidence",
        "voice.stopped": "llm.finish_reason",  # emitted
        "voice.finish_reason": "llm.finish_reason",  # contract
        "voice.tts_chars": "tts.chars",
        "voice.tts_chars_cut": "tts.chars_cut",
        "voice.tts_cut_reason": "tts.cut_reason",
    }

    # VAS labels every content attribute `text`; the span it hangs off says which text.
    content_keys: ClassVar[dict[Stage, dict[str, str]]] = {
        Stage.STT: {"text": "transcript"},
        Stage.LLM: {"text": "llm_raw"},
        Stage.TTS: {"text": "llm_spoken"},
        Stage.PLAYOUT: {"text": "llm_spoken"},
    }

    def check_schema(self, resource: dict) -> None:
        schema = int(resource.get("voice.schema_version") or 0)
        if schema > MAX_SCHEMA:
            raise UnsupportedSchema(f"voice-cascade schema_version {schema} > {MAX_SCHEMA}")
        if schema < 1:  # producer has not started stamping it — parse anyway
            log.warning("voice-cascade sent no voice.schema_version; assuming v%d", MAX_SCHEMA)

    def derive(self, attrs: dict, stage: Stage) -> dict:
        # `voice.outcome` replaced the contract's two booleans. A failed turn also
        # reports `done` — a known producer bug (semantics doc §4.3).
        if stage is Stage.TURN:
            attrs.update(_OUTCOME_FLAGS.get(str(attrs.get("voice.outcome")), {}))
        return attrs

    def header(self, root: dict, resource: dict) -> CallHeader:
        r = attrs_to_dict(root.get("attributes"))
        end = span_end_ns(root)
        return CallHeader(
            call_id=str(r.get("voice.call_id") or root.get("traceId") or ""),
            source=resource.get("service.name", SERVICE_NAME),
            environment=resource.get("deployment.environment", "prod"),
            started_at=_dt(span_start_ns(root)),
            ended_at=_dt(end) if end is not None else None,
            engine=r.get("voice.engine"),
            carrier=r.get("voice.carrier"),
            # gen_ai.provider.name means STT here and LLM on llm.generate (doc §4.1).
            stt_provider=r.get("voice.stt.provider") or r.get("gen_ai.provider.name"),
            llm_provider=r.get("voice.llm.provider"),
            tts_provider=r.get("voice.tts.provider"),
            voice=r.get("voice.tts_voice") or r.get("voice.voice"),
            template_sha256=r.get("voice.prompt.template_sha256"),
            llm_model=None,  # VAS has no model field; the provider string embeds it
            labels=_labels(r),
            counters=_counters(r),
        )


_OUTCOME_FLAGS = {
    "interrupted": {"turn.interrupted": True},
    "empty": {"turn.abandoned": True},
}


def _labels(r: dict[str, Any]) -> dict:
    return {k: r[f"voice.{k}"] for k in ("tenant_id", "campaign_id")
            if r.get(f"voice.{k}") is not None}


def _counters(r: dict[str, Any]) -> dict:
    keys = {
        "stt_segments_heard": "voice.stt.segments_heard",
        "stt_segments_overheard": "voice.stt.segments_overheard",
        "stt_segments_dropped": "voice.stt.segments_dropped",
        "turns": "voice.turns",
    }
    return {out: r[src] for out, src in keys.items() if r.get(src) is not None}
