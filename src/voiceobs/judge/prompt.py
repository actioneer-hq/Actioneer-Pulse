"""Build the chat messages for the post-call judge. The output contract is stated in the
system prompt (committed default in llm/prompts.py, or a per-tenant override) and enforced by
JudgeOutput on the way back."""

from __future__ import annotations

import json

from voiceobs.judge.failure_schema import FailureAnalysis
from voiceobs.judge.schema import JudgeOutput
from voiceobs.llm import LLMRole, default_prompt


def _params_block(params: dict | None) -> str:
    """The per-call template values, so the judge evaluates against what the prompt was ACTUALLY
    rendered with (real name/amount/date) instead of the template's example defaults. Empty when the
    agent isn't parameterized."""
    if not params:
        return ""
    lines = "\n".join(f"- {k}: {v}" for k, v in params.items())
    return (
        "CALL PARAMETERS (the real values this call's prompt was rendered with — treat these as "
        f"ground truth, not errors, if the agent speaks them):\n{lines}\n\n"
    )


def _messages(system: str, schema_model, script, transcript, guardrails, params=None) -> list[dict]:
    # Full schema (not just properties) so the model sees each enum's allowed values, which
    # live under $defs — otherwise it invents values like "AGENT"/"POOR".
    schema = json.dumps(schema_model.model_json_schema(), indent=0)
    user = (
        f"SCRIPT:\n{script or '(none provided)'}\n\n"
        f"GUARDRAILS:\n{guardrails or '(none provided)'}\n\n"
        f"{_params_block(params)}"
        f"TRANSCRIPT:\n{_render(transcript)}"
    )
    # replace, not .format — a tenant's custom prompt may contain unrelated braces.
    return [
        {"role": "system", "content": system.replace("{schema}", schema)},
        {"role": "user", "content": user},
    ]


def build_messages(
    script: str | None, transcript: dict, guardrails: str | None = None,
    prompt: str | None = None, params: dict | None = None,
) -> list[dict]:
    """Messages for the post-call judge (JudgeOutput)."""
    return _messages(prompt or default_prompt(LLMRole.POST_CALL_ANALYSIS),
                     JudgeOutput, script, transcript, guardrails, params)


def build_failure_messages(
    script: str | None, transcript: dict, guardrails: str | None = None,
    prompt: str | None = None, params: dict | None = None,
) -> list[dict]:
    """Messages for the failure-analysis LLM (FailureAnalysis) — same context, its own schema."""
    return _messages(prompt or default_prompt(LLMRole.FAILURE_ANALYSIS),
                     FailureAnalysis, script, transcript, guardrails, params)


def _render(transcript: dict) -> str:
    lines = transcript.get("lines")
    if lines:
        return "\n".join(f"{ln['role']}: {ln['text']}" for ln in lines)
    return transcript.get("text") or "(empty)"
