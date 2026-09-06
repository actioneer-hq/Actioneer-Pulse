"""Per-frame dBFS energy profile per channel — the continuous VAD signal, kept whole
instead of thresholded away. Persisted for failure analysis (soft barge-ins, trailing/
cut-off TTS, latency-within-turn) that the binary utterance segmentation can't express.

Encoding: LE float32, one value per `frame_ms` frame (same framing as the VAD). Pure
silence (rms == 0 -> -inf) is floored to SILENCE_FLOOR_DBFS so the series stays finite
and JSON/float32-safe. Reconstruct time as ``t = i * frame_ms / 1000``."""

from __future__ import annotations

import numpy as np

from voiceobs.core.audio.vad import FRAME_MS, frame_rms_dbfs

SILENCE_FLOOR_DBFS = -120.0


def channel_energy(samples: np.ndarray, sample_rate: int, frame_ms: float = FRAME_MS) -> bytes:
    """dBFS-per-frame series for one channel, as LE float32 bytes (empty if no full frame)."""
    frame_len = max(1, int(sample_rate * frame_ms / 1000.0))
    dbfs = frame_rms_dbfs(samples, frame_len)
    if dbfs.size == 0:
        return b""
    dbfs = np.nan_to_num(dbfs, neginf=SILENCE_FLOOR_DBFS, posinf=0.0)
    return dbfs.astype("<f4").tobytes()
