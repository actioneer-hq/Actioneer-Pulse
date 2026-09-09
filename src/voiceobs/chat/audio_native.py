"""The audio-native sub-call behind the chat agents' `audio_native_llm` tool.

Opt-in (enabled ⇔ the AUDIO_NATIVE role's key is set). Given ONE call, fetch its caller/agent audio,
send it plus the agent's question to a BYO audio-in model as an OpenAI-style `input_audio` multimodal
message, and return the model's text. any-llm forwards the message content untouched, so this reaches
any OpenAI-compatible audio endpoint (GPT-4o-audio, a server fronting Qwen2.5-Omni/Kimi-Audio) through
the existing gateway. Never raises into the agent — failures come back as a short string."""

from __future__ import annotations

import base64
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.config import resolve_llm
from voiceobs.db.models import Call, Media
from voiceobs.llm import gateway
from voiceobs.llm.roles import LLMRole
from voiceobs.storage import fetch_bytes, resolve_creds

log = logging.getLogger(__name__)

# Cap the audio we send so a long call can't blow past the model's input limit (rough: ~10 MB of WAV).
_MAX_AUDIO_BYTES = 10 * 1024 * 1024


def enabled() -> bool:
    return resolve_llm(LLMRole.AUDIO_NATIVE) is not None


def analyze(db: Session, call: Call, user_prompt: str) -> str:
    """Answer `user_prompt` about `call`'s audio using the BYO audio-native model, or a short
    explanation string if it can't run."""
    resolved = resolve_llm(LLMRole.AUDIO_NATIVE)
    if resolved is None:
        return "audio analysis unavailable: no audio-native model configured"
    try:
        parts = _audio_parts(db, call)
    except Exception as e:  # noqa: BLE001 — storage/decode issues must not break the chat turn
        log.warning("audio_native: fetch failed for %s: %s", call.external_call_id, e)
        return f"audio analysis unavailable: could not load audio ({e})"
    if not parts:
        return "audio analysis unavailable: no audio is registered for this call"

    content = [{"type": "text", "text": user_prompt + _channel_note(parts)}, *[p for _, p in parts]]
    messages = [
        {"role": "system", "content": resolved.prompt},
        {"role": "user", "content": content},
    ]
    try:
        resp = gateway.complete(resolved, messages)
        return resp.choices[0].message.content or "(the audio model returned no text)"
    except Exception as e:  # noqa: BLE001 — surface, never raise into the agent loop
        log.warning("audio_native: model call failed for %s: %s", call.external_call_id, e)
        return f"audio analysis unavailable: model call failed ({e})"


def _audio_parts(db: Session, call: Call) -> list[tuple[str, dict]]:
    """(channel_label, input_audio content-part) for the call. Prefers separate caller/agent mono
    tracks; falls back to the single stereo `audio`. Returns [] if nothing usable."""
    kinds = {m.kind: m for m in db.scalars(select(Media).where(Media.call_id == call.id))}
    creds = resolve_creds(db, call.agent_id)
    out: list[tuple[str, dict]] = []
    caller, agent = kinds.get("audio_caller"), kinds.get("audio_agent")
    if caller and caller.uri and agent and agent.uri:
        out.append(("caller", _part(fetch_bytes(caller.uri, creds))))
        out.append(("agent", _part(fetch_bytes(agent.uri, creds))))
    else:
        stereo = kinds.get("audio")
        if stereo and stereo.uri:
            out.append(("stereo", _part(fetch_bytes(stereo.uri, creds))))
    return [(label, p) for label, p in out if p is not None]


def _part(wav: bytes | None) -> dict | None:
    if not wav or len(wav) > _MAX_AUDIO_BYTES:
        return None
    return {"type": "input_audio",
            "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}


def _channel_note(parts: list[tuple[str, dict]]) -> str:
    labels = [label for label, _ in parts]
    if labels == ["stereo"]:
        return "\n\n(Audio: one stereo file — channel 0 = caller, channel 1 = agent.)"
    return f"\n\n(Audio attached, one clip per speaker: {', '.join(labels)}.)"
