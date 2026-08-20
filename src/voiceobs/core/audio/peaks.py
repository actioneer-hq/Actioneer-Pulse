"""Waveform peaks for the viewer — LE int16 (min, max) pairs per channel,
`peaks_per_second` buckets/sec (4 bytes/bucket)."""

from __future__ import annotations

import numpy as np


def channel_peaks(samples: np.ndarray, sample_rate: int, peaks_per_second: int) -> bytes:
    """(min,max) int16 pairs, ``peaks_per_second`` buckets/sec, as LE int16 bytes."""
    if samples.size == 0 or peaks_per_second <= 0:
        return b""
    bucket_len = max(1, sample_rate // peaks_per_second)
    n_buckets = int(np.ceil(samples.size / bucket_len))
    pad = n_buckets * bucket_len - samples.size
    if pad:
        samples = np.concatenate([samples, np.zeros(pad, dtype=samples.dtype)])
    grid = samples.reshape(n_buckets, bucket_len)
    mins = grid.min(axis=1).astype("<i2")
    maxs = grid.max(axis=1).astype("<i2")
    interleaved = np.empty(n_buckets * 2, dtype="<i2")
    interleaved[0::2] = mins
    interleaved[1::2] = maxs
    return interleaved.tobytes()
