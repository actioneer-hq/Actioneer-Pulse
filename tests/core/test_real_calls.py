"""Robustness/plausibility over the real 51-call stereo corpus (gitignored, pulled
from S3). Skips if absent, so CI without the corpus still passes. Asserts sane
ranges, not exact values — capture_coverage isn't reconstructable from a muxed WAV."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voiceobs.core.audio import analyze_audio
from voiceobs.core.audio.metrics import (
    barge_in_count,
    caller_turn_stats,
    talk_ratio,
    utts_to_intervals,
)
from voiceobs.core.model import AudioRef


def _sides(aa):
    caller = [u for u in aa.utterances if u.channel == "caller"]
    agent_iv = utts_to_intervals([u for u in aa.utterances if u.channel == "agent"])
    return caller, agent_iv

CORPUS = Path(__file__).parent.parent / "fixtures" / "real_calls"
MANIFEST = CORPUS / "manifest.json"

pytestmark = pytest.mark.skipif(
    not MANIFEST.exists(), reason="real-call corpus not present (gitignored)"
)


def _manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text())


def _ref(entry: dict, wav: Path) -> AudioRef:
    return AudioRef(
        uri=str(wav), sha256="x", channels=2, sample_rate=8000,
        duration_s=float(entry["duration_seconds"]),
        channel_map={0: "caller", 1: "agent"},
    )


def test_corpus_present_and_stereo():
    m = _manifest()
    assert len(m) >= 40, "expected the full real-call corpus"
    assert all(e["channels"] == 2 for e in m), "all bridge calls must be stereo"


def test_analyze_runs_on_every_call_without_crashing():
    for e in _manifest():
        wav = CORPUS / e["file"]
        if not wav.exists():
            continue
        aa = analyze_audio(wav.read_bytes(), _ref(e, wav))
        # both channels analysed
        assert set(aa.coverage) == {"caller", "agent"}
        assert set(aa.peaks) == {"caller", "agent"}
        # coverage is a fraction
        for v in aa.coverage.values():
            assert 0.0 <= v <= 1.0


def test_derived_metrics_in_plausible_ranges():
    for e in _manifest():
        wav = CORPUS / e["file"]
        if not wav.exists():
            continue
        dur = float(e["duration_seconds"]) or 1.0
        aa = analyze_audio(wav.read_bytes(), _ref(e, wav))
        caller, agent_iv = _sides(aa)

        # talk ratios are fractions; neither side speaks more than the whole call
        tr = talk_ratio(caller, agent_iv, dur)
        for side in ("caller", "agent"):
            assert 0.0 <= tr.get(side, 0.0) <= 1.0

        # barge-ins are non-negative and bounded by caller utterance count
        assert 0 <= barge_in_count(caller, agent_iv) <= max(caller_turn_stats(caller)["count"], 0)


def test_agent_channel_speaks_on_typical_calls():
    # the AI does most of the talking; agent utterances should exist on most calls
    talked = 0
    total = 0
    for e in _manifest():
        wav = CORPUS / e["file"]
        if not wav.exists():
            continue
        total += 1
        aa = analyze_audio(wav.read_bytes(), _ref(e, wav))
        if any(x.channel == "agent" for x in aa.utterances):
            talked += 1
    assert total > 0
    assert talked / total > 0.8  # agent speaks on the overwhelming majority
