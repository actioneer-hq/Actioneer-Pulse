"""capture_coverage — metric zero. Padding = bit-exact-zero samples (dropped
frames); captured silence carries a noise floor. NB: on a muxed WAV, silence and
carrier-drop are indistinguishable — the true metric needs the ingest frame index."""

from __future__ import annotations

import numpy as np


def channel_coverage(samples: np.ndarray) -> float:
    """Fraction of samples that are real audio rather than zero-padding/absent."""
    if samples.size == 0:
        return 0.0
    non_padding = int(np.count_nonzero(samples))
    return round(non_padding / samples.size, 4)


def padding_mask(samples: np.ndarray) -> np.ndarray:
    """Boolean mask, True where the sample is padding (bit-exact zero)."""
    return samples == 0
