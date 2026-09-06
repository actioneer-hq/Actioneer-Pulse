"""Call the post-call judge model and validate the reply against JudgeOutput. Goes through the
any-llm gateway with native structured output (response_format), so no JSON-scraping or provider
quirks here. Transport/retry is any-llm's job; judge_call records a failure without raising."""

from __future__ import annotations

from voiceobs.config import ResolvedLLM
from voiceobs.judge.schema import JudgeOutput
from voiceobs.llm import gateway


def call_model(resolved: ResolvedLLM, messages: list[dict]) -> JudgeOutput:
    """Return the structured JudgeOutput for one judge turn."""
    resp = gateway.complete(resolved, messages, response_format=JudgeOutput)
    msg = resp.choices[0].message
    parsed = getattr(msg, "parsed", None)
    if isinstance(parsed, JudgeOutput):
        return parsed  # native structured output (already validated + enum-coerced)
    data = parsed if parsed is not None else msg.content
    return (
        JudgeOutput.model_validate(data)
        if isinstance(data, dict)
        else JudgeOutput.model_validate_json(data)
    )
