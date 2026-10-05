"""Map the cascade producer's span names onto Pulse stages.

Unmapped names stay `unknown`. The calculator is the shared one: this file
only renames.
"""

from __future__ import annotations

from typing import ClassVar

from voiceobs.core.model import CallHeader, Stage
from voiceobs.frameworks.generic import OTLPAdapter
from voiceobs.frameworks.otlp import attrs_to_dict, iter_spans


class CascadeAdapter(OTLPAdapter):
    name = "cascade"
    version = 1
    service_name = "voice-cascade"

    stages: ClassVar[dict[str, Stage]] = {
        "voice.call": Stage.CALL,
        "voice.turn": Stage.TURN,
        "caller.speech": Stage.SPEECH,
        "transcript": Stage.STT,
        "llm.generate": Stage.LLM,
        "tts.synthesize": Stage.TTS,
        "agent.playout": Stage.PLAYOUT,
        "tool.execute": Stage.TOOL,
        "net.connect": Stage.NET,
    }

    attr_aliases: ClassVar[dict[str, str]] = {
        "voice.turn_id": "turn.id",
        "voice.turn.trigger": "turn.trigger",
        "voice.turn.index": "turn.index",
        "voice.turn.interrupted": "turn.interrupted",
        "voice.turn.abandoned": "turn.abandoned",
        "voice.stt_language": "stt.language",
        "voice.tts.chars": "tts.chars",
        "voice.tts.chars_cut": "tts.chars_cut",
        "voice.tts.cancelled": "tts.cancelled",
        "voice.tts.cut_reason": "tts.cut_reason",
    }

    def matches(self, payload: dict) -> bool:
        return any(
            res.get("service.name") == self.service_name for res, _ in iter_spans(payload)
        )

    def header(self, root: dict, resource: dict) -> CallHeader:
        base = super().header(root, resource)
        raw = attrs_to_dict(root.get("attributes"))
        labels = dict(base.labels)
        campaign = raw.get("voice.campaign_id")
        if campaign:
            labels["campaign_id"] = str(campaign)
        return base.model_copy(update={
            "call_id": str(raw.get("voice.call_id") or base.call_id),
            "engine": str(raw.get("voice.engine") or "cascade"),
            "carrier": _str(raw.get("voice.carrier")),
            "stt_provider": _str(raw.get("voice.stt_provider")),
            "llm_provider": _str(raw.get("voice.llm_provider")),
            "llm_model": _str(raw.get("voice.llm_model")),
            "tts_provider": _str(raw.get("voice.tts_provider")),
            "voice": _str(raw.get("voice.voice")),
            "template_sha256": _str(raw.get("voice.template_sha256")),
            "labels": labels,
        })


def _str(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
