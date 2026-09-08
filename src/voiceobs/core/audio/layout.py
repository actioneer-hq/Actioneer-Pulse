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

# Above this Pearson correlation the two channels are treated as the same signal (a downmix).
_MIXED_CORR = 0.95
# A channel whose RMS is below this fraction of the louder channel is treated as absent (→ mono).
_SILENT_RATIO = 0.02


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


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    """Absolute Pearson correlation; 0 when either channel has no variance."""
    if a.size < 2 or np.std(a) == 0.0 or np.std(b) == 0.0:
        return 0.0
    return float(abs(np.corrcoef(a, b)[0, 1]))
