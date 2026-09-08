"""BYO diarization client — POST a WAV to a diarization endpoint and get back speaker-labelled
segments. Mirrors groundtruth/stt/client.py's shape: one retry, then None. Never raises.

The endpoint contract (bring-your-own model behind it): a multipart POST of the WAV returns JSON
``{"segments": [{"start": float, "end": float, "speaker": str}, ...], "confidence": float?}``.
Providers that already diarize inside their STT response are handled separately (Phase 4)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

TIMEOUT_S = 300.0  # diarization is slower than STT — a long recording can take minutes


@dataclass(frozen=True)
class DiarizeConfig:
    base_url: str
    model: str
    api_key: str | None = None


@dataclass(frozen=True)
class Segment:
    start: float  # seconds on the audio clock
    end: float
    speaker: str  # opaque label from the model (e.g. "SPEAKER_00")


@dataclass(frozen=True)
class Diarization:
    segments: list[Segment] = field(default_factory=list)
    confidence: float | None = None

    def speakers(self) -> list[str]:
        """Distinct speaker labels in first-appearance order."""
        seen: list[str] = []
        for s in self.segments:
            if s.speaker not in seen:
                seen.append(s.speaker)
        return seen


def diarize(config: DiarizeConfig | None, wav: bytes, *, filename: str = "audio.wav") -> Diarization | None:
    """Diarize one WAV into speaker-labelled segments, or None (no config / call failed)."""
    if config is None or not wav:
        return None
    url = config.base_url.rstrip("/") + "/diarize"
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    data = {"model": config.model}
    files = {"file": (filename, wav, "audio/wav")}

    last: Exception | None = None
    for _ in range(2):
        try:
            resp = httpx.post(url, headers=headers, data=data, files=files, timeout=TIMEOUT_S)
            resp.raise_for_status()
            return _parse(resp.json())
        except Exception as e:  # noqa: BLE001 — best-effort; retry then give up
            last = e
    log.warning("diarization failed: %s", last)
    return None


def _parse(body: dict) -> Diarization:
    segments = [
        Segment(
            start=float(s.get("start", 0.0)),
            end=float(s.get("end", 0.0)),
            speaker=str(s.get("speaker", "")),
        )
        for s in (body.get("segments") or [])
        if isinstance(s, dict) and s.get("end") is not None
    ]
    conf = body.get("confidence")
    return Diarization(segments=segments, confidence=float(conf) if conf is not None else None)
