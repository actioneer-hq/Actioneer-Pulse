"""Channel-layout detection: separated vs mixed vs mono."""

from __future__ import annotations

import io
import wave

import numpy as np

from tests.fixtures.synth import SynthCall
from voiceobs.core.audio.layout import detect_layout


def _stereo_from_channels(ch0: np.ndarray, ch1: np.ndarray, sr: int = 8000) -> bytes:
    inter = np.empty(ch0.size * 2, dtype="<i2")
    inter[0::2], inter[1::2] = ch0, ch1
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(inter.tobytes())
    return out.getvalue()


def _mono(samples: np.ndarray, sr: int = 8000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.astype("<i2").tobytes())
    return out.getvalue()


def _tone(freq: float, start_s: float, end_s: float, n: int, sr: int = 8000) -> np.ndarray:
    x = np.zeros(n, dtype=np.float64)
    lo, hi = int(start_s * sr), int(end_s * sr)
    t = np.arange(lo, hi) / sr
    x[lo:hi] = 20000 * np.sin(2 * np.pi * freq * t)
    return x.astype("<i2")


def test_separated_two_speakers_own_channels():
    # caller talks 0-1s, agent 1-2s — the channels are largely uncorrelated.
    wav = SynthCall(duration_s=2.0, speech=[("caller", 0.0, 1.0, 0.8), ("agent", 1.0, 2.0, 0.8)]).build()
    assert detect_layout(wav) == "separated"


def test_mixed_identical_channels_is_mixed():
    n = 8000 * 2
    both = _tone(220, 0.2, 1.8, n)
    assert detect_layout(_stereo_from_channels(both, both.copy())) == "mixed"


def test_one_silent_channel_is_mono():
    n = 8000 * 2
    active = _tone(220, 0.2, 1.8, n)
    silent = np.zeros(n, dtype="<i2")
    assert detect_layout(_stereo_from_channels(active, silent)) == "mono"


def test_single_channel_is_mono():
    n = 8000 * 2
    assert detect_layout(_mono(_tone(220, 0.2, 1.8, n))) == "mono"
