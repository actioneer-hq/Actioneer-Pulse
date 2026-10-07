"""Script -> Journey with an LLM (structured output), then grounding + standard rules in code.

The model is a port: `extract_journey` takes any `structured(messages, schema) -> instance` callable,
so the host product supplies its own LLM. `pulse_structured(role)` is Pulse's adapter (the any-llm
gateway). Run it on a file:

    python -m voiceobs.journey.extract script.txt > journey.json
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from voiceobs.journey.build import build_journey
from voiceobs.journey.model import Journey, JourneyDraft

T = TypeVar("T", bound=BaseModel)
Structured = Callable[[list[dict], type[T]], T]


def messages(script: str, prompt: str) -> list[dict]:
    return [{"role": "system", "content": prompt},
            {"role": "user", "content": f"SCRIPT:\n<<<\n{script}\n>>>"}]


def extract_journey(script: str, structured: Structured, prompt: str) -> tuple[Journey, JourneyDraft]:
    """Returns the built journey and the raw draft (kept to see what grounding dropped)."""
    draft = structured(messages(script, prompt), JourneyDraft)
    return build_journey(script, draft), draft


def pulse_structured(role=None) -> tuple[Structured, str]:
    """Pulse's LLM adapter for the script_journey role -> (structured call, its prompt)."""
    from voiceobs.config import resolve_llm
    from voiceobs.llm import LLMRole, gateway

    resolved = resolve_llm(role or LLMRole.SCRIPT_JOURNEY)
    if resolved is None:
        raise RuntimeError("script_journey role is not configured (no API key)")

    def call(msgs: list[dict], schema: type[T]) -> T:
        msg = gateway.complete(resolved, msgs, response_format=schema).choices[0].message
        parsed = getattr(msg, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        data = parsed if parsed is not None else msg.content
        return schema.model_validate(data) if isinstance(data, dict) else schema.model_validate_json(data)

    return call, resolved.prompt


def main(argv: list[str]) -> int:  # pragma: no cover — manual tool
    script = Path(argv[1]).read_text(encoding="utf-8")
    structured, prompt = pulse_structured()
    journey, draft = extract_journey(script, structured, prompt)
    out = {"journey": journey.model_dump(by_alias=True),
           "draft": draft.model_dump(by_alias=True)}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
