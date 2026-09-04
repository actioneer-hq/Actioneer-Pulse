"""Reconciliation: WER, timing deltas, and the never-raise contract."""

from __future__ import annotations

from voiceobs.core.model import Turn
from voiceobs.groundtruth import STTConfig, Verdict, reconcile
from voiceobs.groundtruth.text import normalize, wer


def _turn(i, **kw) -> Turn:
    return Turn(turn_index=i, turn_id=f"t{i}", trigger="endpoint", **kw)


# ---- WER ----

def test_wer_identical_and_normalization():
    assert wer("Haan ji, boliye.", "haan ji boliye") == 0.0
    assert normalize("Haan, JI!") == ["haan", "ji"]


def test_wer_counts_word_errors():
    assert wer("the cat sat", "the dog sat") == 1 / 3       # one substitution
    assert wer("", "") == 0.0
    assert wer("", "hi") == 1.0


# ---- timing check (no audio bytes needed) ----

def test_timing_flags_first_audio_beyond_band():
    # reported first audio at 1.0s, audio-measured onset at 1.4s → 400ms delta > 150ms band
    turns = [_turn(0, tts_first_audio_at=1.0, audio_out_start_s=1.4)]
    report = reconcile(turns)
    mats = report.material()
    assert "timing" in report.layers_run
    assert len(mats) == 1
    assert mats[0].field == "first_audio_ms" and mats[0].delta == 400.0
    assert mats[0].verdict == Verdict.MATERIAL


def test_timing_within_band_is_not_a_discrepancy():
    turns = [_turn(0, tts_first_audio_at=1.0, audio_out_start_s=1.05)]  # 50ms < band
    assert reconcile(turns).material() == []


def test_missing_fields_contribute_nothing():
    assert reconcile([_turn(0)]).material() == []  # no audio/first-audio times → nothing


# ---- transcript check (mock STT) ----

def test_transcript_wer_flags_divergence(monkeypatch):
    import voiceobs.groundtruth.service as rc

    monkeypatch.setattr(rc, "transcribe", lambda cfg, wav, **k: _Tr("totally different words here"))
    turns = [_turn(0, transcript="hello how are you today")]
    report = reconcile(turns, caller_wav=b"wav", stt=STTConfig("https://x/v1", "whisper-1"))
    mats = [d for d in report.material() if d.field == "caller_wer"]
    assert mats and mats[0].verdict == Verdict.MATERIAL


def test_transcript_skipped_without_stt():
    report = reconcile([_turn(0, transcript="hi")], caller_wav=b"wav", stt=None)
    assert "transcript" not in report.layers_run


def test_reconcile_never_raises_on_bad_stt(monkeypatch):
    import voiceobs.groundtruth.service as rc

    def boom(*a, **k):
        raise RuntimeError("stt exploded")
    monkeypatch.setattr(rc, "transcribe", boom)
    # must not propagate — returns a report, transcript layer just didn't produce
    report = reconcile([_turn(0, transcript="hi")], caller_wav=b"wav",
                       stt=STTConfig("https://x/v1", "m"))
    assert report is not None


class _Tr:
    def __init__(self, text):
        self.text = text
        self.words = []
