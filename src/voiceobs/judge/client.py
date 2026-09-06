"""Call the post-call judge model and validate the reply against JudgeOutput, via the any-llm
gateway with native structured output (response_format).

Failure handling: the post-call analysis is retried up to `_MAX_ATTEMPTS` times on any
model/parse error before giving up (judge_call then records a `failed` status, never raises)."""

from __future__ import annotations

import logging

from voiceobs.config import ResolvedLLM
from voiceobs.judge.schema import JudgeOutput
from voiceobs.llm import gateway

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3  # post-call analysis retries transient model/output errors


def call_model(resolved: ResolvedLLM, messages: list[dict]) -> JudgeOutput:
    """Return the structured JudgeOutput for one judge turn, retrying on error."""
    last: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
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
        except Exception as e:  # noqa: BLE001 — retry model/parse errors, then surface
            last = e
            log.warning("judge attempt %d/%d failed: %s", attempt, _MAX_ATTEMPTS, e)
    raise RuntimeError(f"judge model call failed after {_MAX_ATTEMPTS} attempts: {last}")
