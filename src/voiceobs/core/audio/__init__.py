"""Layer 1 — analyze_audio. Produces the AudioAnalysis primitives (utterances,
peaks, coverage, quality). Derived metrics live in metrics.py; join() wraps them."""

from __future__ import annotations

import numpy as np

from voiceobs.core.audio.coverage import channel_coverage, padding_mask
from voiceobs.core.audio.decode import decode_wav
from voiceobs.core.audio.energy import channel_energy
from voiceobs.core.audio.peaks import channel_peaks
from voiceobs.core.audio.quality import channel_quality
from voiceobs.core.audio.vad import detect_utterances
from voiceobs.core.config import MetricConfig
from voiceobs.core.model import AudioAnalysis, AudioRef, Utterance

__all__ = ["analyze_audio", "padding_intervals_for"]


def analyze_audio(audio: bytes, ref: AudioRef, cfg: MetricConfig | None = None) -> AudioAnalysis:
    """Decode a stereo (or mono) PCM16 WAV and compute the audio primitives."""
    cfg = cfg or MetricConfig()
    decoded = decode_wav(audio, ref.channel_map)
    sr = decoded.sample_rate

    utterances: list[Utterance] = []
    peaks: dict[str, bytes] = {}
    energy: dict[str, bytes] = {}
    coverage: dict[str, float] = {}
    quality: dict[str, dict] = {}

    for speaker, samples in decoded.channels.items():
        utterances.extend(
            detect_utterances(samples, speaker, sr, cfg.vad_threshold_dbfs)
        )
        peaks[speaker] = channel_peaks(samples, sr, cfg.peaks_per_second)
        energy[speaker] = channel_energy(samples, sr, cfg.energy_frame_ms)
        coverage[speaker] = channel_coverage(samples)
        quality[speaker] = channel_quality(samples, sr, clip_dbfs=cfg.clip_dbfs)

    return AudioAnalysis(
        utterances=sorted(utterances, key=lambda u: (u.t_start, u.channel)),
        peaks=peaks,
        energy=energy,
        coverage=coverage,
        quality=quality,
    )


def padding_intervals_for(
    audio: bytes, ref: AudioRef, channel: str = "caller"
) -> list[tuple[float, float]]:
    """Padding (carrier-absent) intervals on one channel, seconds from t0.

    Used by ``dead_air_s`` to exclude dropped-frame regions from silence.
    """
    decoded = decode_wav(audio, ref.channel_map)
    samples = decoded.channels.get(channel)
    if samples is None or samples.size == 0:
        return []
    mask = padding_mask(samples)
    sr = decoded.sample_rate
    return _mask_to_intervals(mask, sr)


def _mask_to_intervals(mask: np.ndarray, sample_rate: int) -> list[tuple[float, float]]:
    if not mask.any():
        return []
    edges = np.diff(mask.astype(np.int8))
    starts = np.flatnonzero(edges == 1) + 1
    ends = np.flatnonzero(edges == -1) + 1
    if mask[0]:
        starts = np.r_[0, starts]
    if mask[-1]:
        ends = np.r_[ends, mask.size]
    return [(round(s / sample_rate, 4), round(e / sample_rate, 4)) for s, e in zip(starts, ends)]
