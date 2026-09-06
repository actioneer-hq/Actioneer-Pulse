"""Report types + tolerance policy invariants."""

from __future__ import annotations

from voiceobs.groundtruth import (
    DEFAULT_POLICY,
    AudioReport,
    Dimension,
    Discrepancy,
    Verdict,
)


def test_material_filters_to_confident_disagreements():
    ds = [
        Discrepancy(dimension=Dimension.VOICE_TO_VOICE, field="v2v", verdict=Verdict.AGREE),
        Discrepancy(dimension=Dimension.VOICE_TO_VOICE, field="v2v", verdict=Verdict.MATERIAL,
                    reported=800, measured=1200, delta=400, confidence=0.9),
        Discrepancy(dimension=Dimension.TRANSCRIPT, field="wer", verdict=Verdict.UNVERIFIABLE),
    ]
    report = AudioReport(discrepancies=ds, layers_run=["decode", "vad", "v2v"])
    assert len(report.material()) == 1
    assert report.material()[0].measured == 1200


def test_default_policy_has_bands():
    assert DEFAULT_POLICY.first_audio_band_ms > 0
    assert 0 < DEFAULT_POLICY.min_coverage <= 1
    assert 0 < DEFAULT_POLICY.transcript_wer_band < 1
