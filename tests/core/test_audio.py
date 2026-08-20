"""Layer-1 audio tests against synthetic WAVs with known ground truth."""

from __future__ import annotations

from tests.fixtures.synth import SynthCall
from voiceobs.core.audio import analyze_audio, padding_intervals_for
from voiceobs.core.audio.metrics import (
    barge_in_count,
    dead_air_s,
    response_latencies,
    talk_ratio,
    turn_stats,
)
from voiceobs.core.config import MetricConfig
from voiceobs.core.model import AudioRef


def _ref(channel_map=None, duration=10.0) -> AudioRef:
    return AudioRef(
        uri="mem://synth", sha256="x", channels=2, sample_rate=8000,
        duration_s=duration, channel_map=channel_map or {0: "caller", 1: "agent"},
    )


def test_pure_silence_no_utterances_full_coverage():
    # captured silence (noise floor, non-zero) -> no speech, but coverage ~1.0
    call = SynthCall(duration_s=5.0, speech=[], padding=[])
    audio = call.build()
    aa = analyze_audio(audio, _ref(duration=5.0))
    assert aa.utterances == []
    assert aa.coverage["caller"] > 0.99  # noise floor is real audio, not padding
    assert aa.coverage["agent"] > 0.99


def test_padding_drops_coverage_but_is_not_dead_air():
    # caller channel silent-with-padding for the middle 4s of a 10s call
    call = SynthCall(
        duration_s=10.0,
        speech=[("agent", 1.0, 3.0, 0.8)],
        padding=[("caller", 3.0, 7.0)],
    )
    audio = call.build()
    ref = _ref(duration=10.0)
    aa = analyze_audio(audio, ref)
    # 4s of 10s padded on caller -> coverage ~0.6
    assert 0.55 < aa.coverage["caller"] < 0.65
    assert aa.coverage["agent"] > 0.99

    # dead_air must EXCLUDE the padded region (capture problem, not silence)
    pad = padding_intervals_for(audio, ref, "caller")
    assert pad and abs(pad[0][0] - 3.0) < 0.05 and abs(pad[0][1] - 7.0) < 0.05
    da_with_pad = dead_air_s(aa.utterances, 10.0, min_gap_s=1.0, padding_intervals=pad)
    da_without = dead_air_s(aa.utterances, 10.0, min_gap_s=1.0)
    assert da_with_pad < da_without  # padding excluded shrinks dead air


def test_barge_in_measured_on_overlap():
    # caller starts speaking at 2.5s while agent speaks 2.0-4.0 -> 1 barge-in
    call = SynthCall(
        duration_s=8.0,
        speech=[
            ("agent", 2.0, 4.0, 0.8),
            ("caller", 2.5, 3.2, 0.8),  # cuts in
            ("caller", 6.0, 6.8, 0.8),  # clean, no overlap
        ],
    )
    aa = analyze_audio(call.build(), _ref(duration=8.0))
    assert barge_in_count(aa.utterances) == 1


def test_response_latency_series():
    # caller 1.0-2.0, agent responds at 2.5 -> latency 0.5s
    call = SynthCall(
        duration_s=6.0,
        speech=[("caller", 1.0, 2.0, 0.8), ("agent", 2.5, 4.0, 0.8)],
    )
    aa = analyze_audio(call.build(), _ref(duration=6.0))
    lats = response_latencies(aa.utterances)
    assert len(lats) == 1
    assert abs(lats[0] - 0.5) < 0.06  # frame-quantised


def test_talk_ratio_and_turn_stats():
    call = SynthCall(
        duration_s=10.0,
        speech=[
            ("caller", 0.0, 2.0, 0.8),
            ("agent", 3.0, 7.0, 0.8),
        ],
    )
    aa = analyze_audio(call.build(), _ref(duration=10.0))
    tr = talk_ratio(aa.utterances, 10.0)
    assert abs(tr["caller"] - 0.20) < 0.03  # 2s / 10s
    assert abs(tr["agent"] - 0.40) < 0.03  # 4s / 10s
    stats = turn_stats(aa.utterances)
    assert stats["caller"]["count"] == 1
    assert stats["agent"]["count"] == 1
    assert abs(stats["agent"]["max_s"] - 4.0) < 0.06


def test_channel_map_is_honoured_not_index():
    # invert the map: index 0 is AGENT here. Speech on index-0 must read as agent.
    call = SynthCall(
        duration_s=5.0,
        speech=[("agent", 1.0, 3.0, 0.8)],  # 'agent' label -> whichever index maps
        channel_map={0: "agent", 1: "caller"},
    )
    ref = _ref(channel_map={0: "agent", 1: "caller"}, duration=5.0)
    aa = analyze_audio(call.build(), ref)
    speakers = {u.channel for u in aa.utterances}
    assert speakers == {"agent"}


def test_clipping_detected_in_quality():
    call = SynthCall(duration_s=3.0, speech=[("caller", 0.5, 1.5, 1.0)])  # amp 1.0 -> clips
    aa = analyze_audio(call.build(), _ref(duration=3.0), MetricConfig())
    assert aa.quality["caller"]["clipping_ratio"] > 0.0
    assert aa.quality["caller"]["peak_dbfs"] > -1.0


def test_peaks_shape():
    call = SynthCall(duration_s=2.0, speech=[("caller", 0.0, 2.0, 0.5)])
    aa = analyze_audio(call.build(), _ref(duration=2.0), MetricConfig(peaks_per_second=50))
    # 2s * 50 buckets/s * 2 int16 * 2 bytes = 400 bytes
    assert len(aa.peaks["caller"]) == 2 * 50 * 2 * 2
