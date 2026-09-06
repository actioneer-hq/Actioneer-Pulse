"""Per-channel energy VAD -> Utterances. Frame-based RMS gate; sub-hangover
pauses don't split a word. Energy VAD is coarse — STT word timings are the
eventual upgrade (§4.4)."""

from __future__ import annotations

import numpy as np

from voiceobs.core.audio.decode import INT16_FULL_SCALE
from voiceobs.core.model import Utterance

FRAME_MS = 20.0
HANGOVER_S = 0.20  # merge speech runs separated by <= this (intra-utterance pause)
MIN_UTTERANCE_S = 0.10  # drop blips shorter than this


def frame_rms_dbfs(samples: np.ndarray, frame_len: int) -> np.ndarray:
    """dBFS per fixed-length frame. Trailing partial frame is dropped."""
    n = samples.size // frame_len
    if n == 0:
        return np.array([], dtype=np.float64)
    trimmed = samples[: n * frame_len].astype(np.float64).reshape(n, frame_len)
    rms = np.sqrt(np.mean(np.square(trimmed), axis=1))
    with np.errstate(divide="ignore"):
        dbfs = 20.0 * np.log10(rms / INT16_FULL_SCALE)
    return dbfs  # -inf where rms == 0


def detect_utterances(
    samples: np.ndarray,
    channel: str,
    sample_rate: int,
    threshold_dbfs: float,
    frame_ms: float = FRAME_MS,
    hangover_s: float = HANGOVER_S,
    min_utterance_s: float = MIN_UTTERANCE_S,
) -> list[Utterance]:
    """Contiguous speech regions on one channel as Utterances (seconds from t0)."""
    frame_len = max(1, int(sample_rate * frame_ms / 1000.0))
    dbfs = frame_rms_dbfs(samples, frame_len)
    if dbfs.size == 0:
        return []

    speech = dbfs > threshold_dbfs
    frame_s = frame_len / sample_rate
    hangover_frames = round(hangover_s / frame_s)

    utterances: list[Utterance] = []
    start: int | None = None
    gap = 0
    for i, is_speech in enumerate(speech):
        if is_speech:
            if start is None:
                start = i
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap > hangover_frames:
                    end = i - gap + 1
                    utterances.append(_mk(channel, start, end, frame_s))
                    start = None
                    gap = 0
    if start is not None:
        utterances.append(_mk(channel, start, len(speech), frame_s))

    return [u for u in utterances if (u.t_end - u.t_start) >= min_utterance_s]


def _mk(channel: str, start_frame: int, end_frame: int, frame_s: float) -> Utterance:
    return Utterance(
        channel=channel,
        t_start=round(start_frame * frame_s, 4),
        t_end=round(end_frame * frame_s, 4),
    )
