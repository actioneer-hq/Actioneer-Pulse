"""WAV decode + channel split by AudioRef.channel_map — never assume ch0=caller."""

from __future__ import annotations

import io
import wave

import numpy as np
from pydantic import BaseModel, ConfigDict

INT16_FULL_SCALE = 32768.0


class DecodedAudio(BaseModel):
    """Per-channel int16 samples keyed by speaker, plus the stream geometry."""

    # arbitrary_types_allowed: numpy arrays are not a Pydantic-native type.
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    channels: dict[str, np.ndarray]  # "caller"/"agent" -> int16 samples
    sample_rate: int
    n_frames: int  # samples per channel

    @property
    def duration_s(self) -> float:
        return self.n_frames / self.sample_rate if self.sample_rate else 0.0


def decode_wav(audio: bytes, channel_map: dict[int, str]) -> DecodedAudio:
    """Decode a PCM16 WAV and split into named channels via ``channel_map``.

    Supports mono and stereo. For mono, ``channel_map`` should map index 0 to a
    speaker; the other side is simply absent (mono -> single-channel analysis).
    """
    with wave.open(io.BytesIO(audio), "rb") as w:
        n_channels = w.getnchannels()
        sample_rate = w.getframerate()
        sampwidth = w.getsampwidth()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)

    if sampwidth != 2:
        raise ValueError(f"expected PCM16 (2-byte samples), got sampwidth={sampwidth}")

    flat = np.frombuffer(raw, dtype="<i2")
    if n_channels > 1:
        # interleaved -> (n_frames, n_channels)
        deint = flat.reshape(-1, n_channels)
    else:
        deint = flat.reshape(-1, 1)

    channels: dict[str, np.ndarray] = {}
    for idx, speaker in channel_map.items():
        if idx < n_channels:
            channels[speaker] = np.ascontiguousarray(deint[:, idx])

    return DecodedAudio(channels=channels, sample_rate=sample_rate, n_frames=deint.shape[0])


def rms_dbfs(samples: np.ndarray) -> float:
    """RMS level in dBFS. Silence (all-zero) -> -inf."""
    if samples.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if rms <= 0.0:
        return float("-inf")
    return 20.0 * float(np.log10(rms / INT16_FULL_SCALE))
