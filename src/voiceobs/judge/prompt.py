"""Build the chat messages for the judge. The output contract is stated here and
enforced by JudgeOutput on the way back."""

from __future__ import annotations

import json

from voiceobs.judge.schema import JudgeOutput

_SYSTEM = (
    "You are a call-quality judge for outbound voice-agent calls. You are given the "
    "agent's script and the call transcript. Return ONLY a JSON object matching this "
    "schema, no prose:\n"
    "{schema}\n\n"
    "Rules:\n"
    "- primary_language is the most-spoken language; secondary_languages lists the rest.\n"
    "- callback_time is filled only if callback_requested and a time is stated, else null.\n"
    "- summary is at most 30 words, and only when a human or voicemail actually spoke; "
    "otherwise null.\n"
    "- Use only the allowed enum values."
)


def build_messages(script: str | None, transcript: dict) -> list[dict]:
    schema = json.dumps(JudgeOutput.model_json_schema()["properties"], indent=0)
    user = (
        f"SCRIPT:\n{script or '(none provided)'}\n\n"
        f"TRANSCRIPT:\n{_render(transcript)}"
    )
    return [
        {"role": "system", "content": _SYSTEM.format(schema=schema)},
        {"role": "user", "content": user},
    ]


def _render(transcript: dict) -> str:
    lines = transcript.get("lines")
    if lines:
        return "\n".join(f"{ln['role']}: {ln['text']}" for ln in lines)
    return transcript.get("text") or "(empty)"
