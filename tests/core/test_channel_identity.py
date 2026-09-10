"""Channel identity by noise floor: the digitally-clean channel is the agent (TTS), the channel
carrying ambient noise is the human caller."""

from __future__ import annotations

import io
import wave

import numpy as np

from voiceobs.core.audio.layout import identify_agent_channel

SR = 8000


def _speech(n: int, lo_s: float, hi_s: float) -> np.ndarray:
    x = np.zeros(n, dtype=np.float64)
    lo, hi = int(lo_s * SR), int(hi_s * SR)
    t = np.arange(lo, hi) / SR
    x[lo:hi] = 18000 * np.sin(2 * np.pi * 220 * t)
    return x


def _stereo(ch0: np.ndarray, ch1: np.ndarray) -> bytes:
    inter = np.empty(ch0.size * 2, dtype="<i2")
    inter[0::2] = np.clip(ch0, -32767, 32767).astype("<i2")
    inter[1::2] = np.clip(ch1, -32767, 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(inter.tobytes())
    return out.getvalue()


def test_agent_channel_is_the_clean_one():
    n = 3 * SR
    rng = np.random.default_rng(0)
    human_floor = rng.normal(0, 150, n)  # ambient noise everywhere
    human = human_floor + _speech(n, 0.0, 1.0)  # caller talks 0–1s
    agent = _speech(n, 1.5, 2.5)  # agent talks 1.5–2.5s, pure digital silence otherwise

    # caller on ch0, agent on ch1 → agent is channel 1
    assert identify_agent_channel(_stereo(human, agent)) == 1
    # swap the sides → agent is channel 0
    assert identify_agent_channel(_stereo(agent, human)) == 0


def test_undecidable_returns_none():
    n = 3 * SR
    rng = np.random.default_rng(1)
    a = rng.normal(0, 150, n) + _speech(n, 0.0, 1.0)
    b = rng.normal(0, 150, n) + _speech(n, 1.5, 2.5)  # both channels carry ambient noise
    assert identify_agent_channel(_stereo(a, b)) is None


def test_mono_returns_none():
    n = 2 * SR
    mono = _speech(n, 0.0, 1.0)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(mono.clip(-32767, 32767).astype("<i2").tobytes())
    assert identify_agent_channel(out.getvalue()) is None
