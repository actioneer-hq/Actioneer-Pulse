"""BYO STT client — POST a WAV to an OpenAI-compatible /audio/transcriptions endpoint and get
back text + word timings. Mirrors judge/client.py's shape: one retry, then None. Never raises."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

TIMEOUT_S = 120.0


@dataclass(frozen=True)
class STTConfig:
    base_url: str
    model: str
    api_key: str | None = None


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconds, on the audio clock
    end: float


@dataclass(frozen=True)
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)


def transcribe(config: STTConfig | None, wav: bytes, *, filename: str = "audio.wav") -> Transcript | None:
    """Transcribe one channel's WAV with word timestamps, or None (no config / call failed).
    OpenAI-compatible: multipart POST with model + response_format=verbose_json +
    timestamp_granularities[]=word."""
    if config is None or not wav:
        return None
    url = config.base_url.rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    data = {
        "model": config.model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    files = {"file": (filename, wav, "audio/wav")}

    for _ in range(2):
        try:
            resp = httpx.post(url, headers=headers, data=data, files=files, timeout=TIMEOUT_S)
            resp.raise_for_status()
            return _parse(resp.json())
        except Exception as e:  # noqa: BLE001 — transcript check is best-effort; retry then give up
            last = e
    log.warning("STT transcription failed: %s", last)
    return None


def _parse(body: dict) -> Transcript:
    words = [
        Word(text=w.get("word", ""), start=float(w.get("start", 0.0)), end=float(w.get("end", 0.0)))
        for w in (body.get("words") or [])
        if isinstance(w, dict)
    ]
    return Transcript(text=body.get("text", ""), words=words)
