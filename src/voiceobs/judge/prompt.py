"""Build the chat messages for the post-call judge. The output contract is stated in the
system prompt (committed default in llm/prompts.py, or a per-tenant override) and enforced by
JudgeOutput on the way back."""

from __future__ import annotations

import json

from voiceobs.judge.schema import JudgeOutput
from voiceobs.llm import LLMRole, default_prompt


def build_messages(
    script: str | None, transcript: dict, guardrails: str | None = None,
    prompt: str | None = None,
) -> list[dict]:
    system = prompt or default_prompt(LLMRole.POST_CALL_ANALYSIS)
    # Full schema (not just properties) so the model sees each enum's allowed values, which
    # live under $defs — otherwise it invents values like "AGENT"/"POOR".
    schema = json.dumps(JudgeOutput.model_json_schema(), indent=0)
    user = (
        f"SCRIPT:\n{script or '(none provided)'}\n\n"
        f"GUARDRAILS:\n{guardrails or '(none provided)'}\n\n"
        f"TRANSCRIPT:\n{_render(transcript)}"
    )
    # replace, not .format — a tenant's custom prompt may contain unrelated braces.
    return [
        {"role": "system", "content": system.replace("{schema}", schema)},
        {"role": "user", "content": user},
    ]


def _render(transcript: dict) -> str:
    lines = transcript.get("lines")
    if lines:
        return "\n".join(f"{ln['role']}: {ln['text']}" for ln in lines)
    return transcript.get("text") or "(empty)"
