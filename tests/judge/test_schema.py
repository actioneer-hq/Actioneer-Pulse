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


def test_failure_block_populated():
    out = JudgeOutput.model_validate({
        **_BASE, "objective_achieved": "not_achieved", "is_failure": True,
        "root_cause": "Agent looped on the same clarifying question.",
        "model_fault": "llm", "model_fault_detail": "ASR was correct; the LLM ignored the answer.",
        "hallucination": True, "hallucination_detail": "Claimed a refund policy that doesn't exist.",
        "suggested_fix": "Add a max-reask guardrail and ground refund claims in the script.",
    })
    assert out.is_failure is True
    assert out.model_fault == "llm"
    assert out.hallucination_detail.startswith("Claimed")
    assert out.suggested_fix


def test_failure_block_cleared_when_not_failure():
    # model returned a root cause etc. but said is_failure=false → the block is wiped
    out = JudgeOutput.model_validate({
        **_BASE, "is_failure": False,
        "root_cause": "stray", "model_fault": "asr", "model_fault_detail": "stray",
        "hallucination": True, "hallucination_detail": "stray", "suggested_fix": "stray",
    })
    assert out.root_cause is None
    assert out.model_fault == "none"
    assert out.model_fault_detail is None
    assert out.hallucination is False
    assert out.hallucination_detail is None
    assert out.suggested_fix is None


def test_model_fault_detail_dropped_when_none():
    out = JudgeOutput.model_validate({
        **_BASE, "is_failure": True, "root_cause": "caller hung up",
        "model_fault": "none", "model_fault_detail": "stray", "suggested_fix": "shorten intro",
    })
    assert out.model_fault == "none"
    assert out.model_fault_detail is None
