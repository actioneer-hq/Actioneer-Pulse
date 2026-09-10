"""Channel-layout detection — the front gate for audio-only analysis.

A recording is one of three layouts:
- ``mono``      — a single channel (both speakers mixed, or only one carried).
- ``separated`` — two channels, each carrying one speaker (telephony / track egress). Per-channel
  VAD attributes speech to caller vs agent directly; no diarization needed.
- ``mixed``     — two channels but both carry both speakers (a downmix / dual-mono). The second
  channel buys nothing, so this needs diarization to attribute speech.

The discriminator between separated and mixed is inter-channel correlation: a true stereo downmix has
near-identical channels (corr ~ 1), while two separate speaker mics are largely uncorrelated (each is
silent while the other talks). A channel that is effectively silent collapses the file to ``mono``.
"""

from __future__ import annotations

import io
import wave

import numpy as np

from voiceobs.core.audio.energy import SILENCE_FLOOR_DBFS
from voiceobs.core.audio.vad import FRAME_MS, frame_rms_dbfs

# Above this Pearson correlation the two channels are treated as the same signal (a downmix).
_MIXED_CORR = 0.95
# A channel whose RMS is below this fraction of the louder channel is treated as absent (→ mono).
_SILENT_RATIO = 0.02
# Channel-identity by noise floor: percentile of per-frame dBFS taken as the "between-speech" level,
# and the minimum gap (dB) between the two channels' floors required to decide who is the agent.
_FLOOR_PERCENTILE = 10.0
_FLOOR_MARGIN_DBFS = 6.0


def detect_layout(audio: bytes) -> str:
    """Classify a PCM16 WAV as ``mono`` | ``separated`` | ``mixed``. Never raises on shape; a body
    that can't be parsed as WAV raises ValueError (caller maps it to a failed analysis)."""
    with wave.open(io.BytesIO(audio), "rb") as w:
        n_channels = w.getnchannels()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
    if n_channels < 2:
        return "mono"

    flat = np.frombuffer(raw, dtype="<i2").reshape(-1, n_channels).astype(np.float64)
    a, b = flat[:, 0], flat[:, 1]
    rms_a, rms_b = _rms(a), _rms(b)
    louder = max(rms_a, rms_b)
    if louder == 0.0:
        return "mono"  # pure silence — nothing to separate
    if min(rms_a, rms_b) < _SILENT_RATIO * louder:
        return "mono"  # one channel is effectively empty → single active track

    return "mixed" if _corr(a, b) >= _MIXED_CORR else "separated"


def _noise_floor_dbfs(samples: np.ndarray, sample_rate: int) -> float:
    """The channel's between-speech level: a low percentile of its per-frame dBFS. Pure-silence
    frames (rms 0 → -inf) are floored to SILENCE_FLOOR_DBFS so the percentile stays finite."""
    frame_len = max(1, int(sample_rate * FRAME_MS / 1000.0))
    dbfs = frame_rms_dbfs(samples, frame_len)
    if dbfs.size == 0:
        return SILENCE_FLOOR_DBFS
    dbfs = np.nan_to_num(dbfs, neginf=SILENCE_FLOOR_DBFS, posinf=0.0)
    return float(np.percentile(dbfs, _FLOOR_PERCENTILE))


def identify_agent_channel(audio: bytes) -> int | None:
    """Which stereo channel is the agent, by noise floor.

    A synthetic (TTS) agent channel is digitally clean between utterances — a near-silent floor —
    while a human caller's channel carries ambient room/line noise. So the channel with the LOWER
    noise floor is the agent. Returns that channel index (0 or 1), or None when it can't be told
    apart confidently: mono, or the two floors are within ``_FLOOR_MARGIN_DBFS`` of each other (a
    downmix, both-clean, or both-noisy recording). Never raises on shape beyond WAV parsing."""
    with wave.open(io.BytesIO(audio), "rb") as w:
        n_channels = w.getnchannels()
        sample_rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if n_channels < 2:
        return None
    flat = np.frombuffer(raw, dtype="<i2").reshape(-1, n_channels).astype(np.float64)
    floor0 = _noise_floor_dbfs(flat[:, 0], sample_rate)
    floor1 = _noise_floor_dbfs(flat[:, 1], sample_rate)
    if abs(floor0 - floor1) < _FLOOR_MARGIN_DBFS:
        return None  # too close to call — leave identity to an explicit channel_map
    return 0 if floor0 < floor1 else 1


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    """Absolute Pearson correlation; 0 when either channel has no variance."""
    if a.size < 2 or np.std(a) == 0.0 or np.std(b) == 0.0:
        return 0.0
    return float(abs(np.corrcoef(a, b)[0, 1]))
