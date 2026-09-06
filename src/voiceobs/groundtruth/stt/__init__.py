"""BYO speech-to-text for transcript verification. An OpenAI-compatible
`/audio/transcriptions` endpoint the client owns (model + key), resolved per-agent from
AgentAudioConfig. Absent or failing → None, never an error (transcript checks skip)."""

from __future__ import annotations

from voiceobs.groundtruth.stt.client import STTConfig, Word, transcribe
from voiceobs.groundtruth.stt.config import resolve_stt

__all__ = ["STTConfig", "Word", "resolve_stt", "transcribe"]
