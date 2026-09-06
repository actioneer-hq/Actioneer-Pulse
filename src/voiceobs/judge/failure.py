"""The failure-analysis LLM — a second model run alongside the judge, doing root-cause analysis.
Its schema (FailureAnalysis) is small, so provider-native structured output is used directly."""

from __future__ import annotations

from voiceobs.config import ResolvedLLM
from voiceobs.judge.failure_schema import FailureAnalysis
from voiceobs.llm import gateway


def analyze_failure(resolved: ResolvedLLM, messages: list[dict]) -> FailureAnalysis:
    """Return the structured FailureAnalysis for one call."""
    resp = gateway.complete(resolved, messages, response_format=FailureAnalysis)
    msg = resp.choices[0].message
    parsed = getattr(msg, "parsed", None)
    if isinstance(parsed, FailureAnalysis):
        return parsed
    data = parsed if parsed is not None else msg.content
    return (
        FailureAnalysis.model_validate(data)
        if isinstance(data, dict)
        else FailureAnalysis.model_validate_json(data)
    )
