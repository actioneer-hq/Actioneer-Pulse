"""JudgeOutput conditional keys + enum coercion."""

from __future__ import annotations

from voiceobs.judge.schema import JudgeOutput

_BASE = {
    "sentiment": "neutral", "objective_achieved": "partial", "answered_by": "human",
    "primary_language": "en", "secondary_languages": [], "script_adherence": "partial",
}


def test_points_kept_when_violation():
    out = JudgeOutput.model_validate({
        **_BASE, "guardrail_violation": True,
        "guardrail_violation_points": ["Left the script", "Skipped caller verification"],
    })
    assert out.guardrail_violation is True
    assert out.guardrail_violation_points == ["Left the script", "Skipped caller verification"]


def test_points_dropped_when_no_violation():
    # model returned points but said no violation → points are cleared (conditional key)
    out = JudgeOutput.model_validate({
        **_BASE, "guardrail_violation": False,
        "guardrail_violation_points": ["stray point the model shouldn't have sent"],
    })
    assert out.guardrail_violation is False
    assert out.guardrail_violation_points == []


def test_defaults_no_violation():
    out = JudgeOutput.model_validate(_BASE)
    assert out.guardrail_violation is False
    assert out.guardrail_violation_points == []
