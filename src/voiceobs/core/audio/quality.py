"""audio_quality per channel — peak/RMS dBFS, clipping, dropout. Dropout =
interior zero-runs (bounded by real audio), not leading/trailing absence."""

from __future__ import annotations

import numpy as np

from voiceobs.core.audio.decode import INT16_FULL_SCALE, rms_dbfs


def channel_quality(
    samples: np.ndarray,
    sample_rate: int,
    clip_dbfs: float = -0.1,
    dropout_min_ms: float = 40.0,
) -> dict:
    """Quality descriptor for one channel."""
    if samples.size == 0:
        return {
            "peak_dbfs": float("-inf"), "rms_dbfs": float("-inf"),
            "clipping_ratio": 0.0, "dropout_count": 0, "dropout_s": 0.0,
        }

    absamp = np.abs(samples.astype(np.float64))
    peak = float(absamp.max())
    peak_dbfs = 20.0 * float(np.log10(peak / INT16_FULL_SCALE)) if peak > 0 else float("-inf")

    clip_level = INT16_FULL_SCALE * (10.0 ** (clip_dbfs / 20.0))
    clipping_ratio = round(float(np.count_nonzero(absamp >= clip_level)) / samples.size, 6)

    dropout_count, dropout_samples = _interior_zero_runs(
        samples, min_len=int(sample_rate * dropout_min_ms / 1000.0)
    )

    return {
        "peak_dbfs": round(peak_dbfs, 2),
        "rms_dbfs": round(rms_dbfs(samples), 2),
        "clipping_ratio": clipping_ratio,
        "dropout_count": dropout_count,
        "dropout_s": round(dropout_samples / sample_rate, 4),
    }


def _interior_zero_runs(samples: np.ndarray, min_len: int) -> tuple[int, int]:
    """Count/measure zero-runs that are bounded by real audio on both sides."""
    nonzero_idx = np.flatnonzero(samples)
    if nonzero_idx.size < 2:
        return 0, 0
    lo, hi = nonzero_idx[0], nonzero_idx[-1]
    interior = samples[lo : hi + 1]
    is_zero = interior == 0
    if not is_zero.any():
        return 0, 0
    # run-length over the interior zero mask
    edges = np.diff(is_zero.astype(np.int8))
    starts = np.flatnonzero(edges == 1) + 1
    ends = np.flatnonzero(edges == -1) + 1
    if is_zero[0]:
        starts = np.r_[0, starts]
    if is_zero[-1]:
        ends = np.r_[ends, is_zero.size]
    runs = ends - starts
    long_runs = runs[runs >= max(1, min_len)]
    return int(long_runs.size), int(long_runs.sum())
