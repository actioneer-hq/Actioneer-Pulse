"""Synthetic stereo PCM16 WAV builder for deterministic audio-metric tests.

Build a call from labelled (channel, start_s, end_s) speech regions plus optional
padding (bit-exact zero) regions, so every metric has a known ground truth.
"""

from __future__ import annotations

import io
import wave

import numpy as np
from pydantic import BaseModel, Field

FULL_SCALE = 32767


class SynthCall(BaseModel):
    duration_s: float
    sample_rate: int = 8000
    # (channel, start_s, end_s, amplitude 0..1)
    speech: list[tuple[str, float, float, float]] = Field(default_factory=list)
    # (channel, start_s, end_s) forced to bit-exact zero (carrier padding/absent)
    padding: list[tuple[str, float, float]] = Field(default_factory=list)
    channel_map: dict[int, str] = Field(default_factory=lambda: {0: "caller", 1: "agent"})
    noise_floor: int = 8  # small non-zero floor so real silence != padding

    def build(self) -> bytes:
        n = int(self.duration_s * self.sample_rate)
        idx = {v: k for k, v in self.channel_map.items()}
        n_ch = len(self.channel_map)
        # start with a low, NON-ZERO noise floor everywhere (captured-but-silent)
        rng = np.random.default_rng(42)
        buf = rng.integers(
            -self.noise_floor, self.noise_floor + 1, size=(n, n_ch), dtype=np.int64
        ).astype(np.int64)
        buf[buf == 0] = self.noise_floor  # guarantee non-zero floor

        t = np.arange(n) / self.sample_rate
        for ch, s, e, amp in self.speech:
            c = idx[ch]
            lo, hi = int(s * self.sample_rate), int(e * self.sample_rate)
            tone = (amp * FULL_SCALE * np.sin(2 * np.pi * 220 * t[lo:hi])).astype(np.int64)
            buf[lo:hi, c] = tone

        for ch, s, e in self.padding:
            c = idx[ch]
            lo, hi = int(s * self.sample_rate), int(e * self.sample_rate)
            buf[lo:hi, c] = 0  # bit-exact zero = padding/absent

        pcm = np.clip(buf, -FULL_SCALE, FULL_SCALE).astype("<i2")
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(n_ch)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(pcm.tobytes())
        return out.getvalue()
