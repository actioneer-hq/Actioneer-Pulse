"""FailureAnalysis — conditional root-cause block + model_fault coercion."""

from __future__ import annotations

from voiceobs.judge.failure_schema import FailureAnalysis


def test_populated_when_failure():
    out = FailureAnalysis.model_validate({
        "is_failure": True,
        "root_cause": "Agent looped on the same clarifying question.",
        "model_fault": "llm", "model_fault_detail": "ASR was correct; the LLM ignored the answer.",
        "hallucination": True, "hallucination_detail": "Claimed a refund policy that doesn't exist.",
        "suggested_fix": "Add a max-reask guardrail and ground refund claims in the script.",
    })
    assert out.is_failure is True
    assert out.model_fault == "llm"
    assert out.hallucination_detail.startswith("Claimed")
    assert out.suggested_fix


def test_block_cleared_when_not_failure():
    out = FailureAnalysis.model_validate({
        "is_failure": False, "root_cause": "stray", "model_fault": "asr",
        "model_fault_detail": "stray", "hallucination": True, "hallucination_detail": "stray",
        "suggested_fix": "stray",
    })
    assert out.root_cause is None
    assert out.model_fault == "none"
    assert out.model_fault_detail is None
    assert out.hallucination is False
    assert out.hallucination_detail is None
    assert out.suggested_fix is None


def test_model_fault_detail_dropped_when_none():
    out = FailureAnalysis.model_validate({
        "is_failure": True, "root_cause": "caller hung up",
        "model_fault": "none", "model_fault_detail": "stray", "suggested_fix": "shorten intro",
    })
    assert out.model_fault == "none"
    assert out.model_fault_detail is None


def test_out_of_vocab_model_fault_coerced():
    out = FailureAnalysis.model_validate({"is_failure": True, "root_cause": "x", "model_fault": "GPU"})
    assert out.model_fault == "other"


def test_defaults():
    out = FailureAnalysis.model_validate({})
    assert out.is_failure is False
    assert out.model_fault == "none"
    assert out.root_cause is None
