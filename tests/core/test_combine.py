"""combine_stereo — two mono WAVs (caller, agent) -> one caller/agent stereo WAV."""

from __future__ import annotations

from tests.fixtures.synth import SynthCall
from voiceobs.core.audio.decode import combine_stereo, decode_wav


def _mono(channel: str, dur: float, speech) -> bytes:
    # a one-channel WAV for `channel` by mapping index 0 to it
    return SynthCall(duration_s=dur, speech=speech,
                     channel_map={0: channel}).build()


def test_combine_puts_caller_left_agent_right():
    caller = _mono("caller", 3.0, [("caller", 0.5, 1.5, 0.8)])
    agent = _mono("agent", 3.0, [("agent", 2.0, 2.8, 0.8)])
    stereo = combine_stereo(caller, agent)

    d = decode_wav(stereo, {0: "caller", 1: "agent"})
    assert set(d.channels) == {"caller", "agent"}
    # caller speech in the first half, agent in the second — channels not swapped
    assert d.channels["caller"][:int(1.5 * 8000)].any()
    assert d.channels["agent"][int(2.0 * 8000):].any()


def test_combine_pads_shorter_channel():
    caller = _mono("caller", 2.0, [])
    agent = _mono("agent", 4.0, [])
    d = decode_wav(combine_stereo(caller, agent), {0: "caller", 1: "agent"})
    assert d.channels["caller"].size == d.channels["agent"].size  # padded to the longer
