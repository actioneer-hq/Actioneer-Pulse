"""LLM half of the journey judge: only what needs words — summary, callback time, unscripted moments
(things the script never prepared the agent for) and wrong values.

It runs in parallel with the decision model and never repeats anything the decision model owns. Prompt order for caching: system + this schema + journey JSON (identical for every call of a
script version) -> cache breakpoint -> call parameters -> transcript.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Unscripted(BaseModel):
    """Something the customer raised that the journey has no branch for — a script gap."""

    turn: int = Field(ge=0)
    what: str
    agent_response_ok: bool


class WrongValue(BaseModel):
    """The agent stated a value that contradicts a call parameter."""

    param: str
    expected: str
    said: str
    turn: int = Field(ge=0)


class LLMJudgment(BaseModel):
    summary: str | None = None     # <= 30 words, only when someone spoke
    unscripted: list[Unscripted] = Field(default_factory=list)
    callback_time: str | None = None
    wrong_values: list[WrongValue] = Field(default_factory=list)


# ── the call ─────────────────────────────────────────────────────────────────────────
def llm_messages(prompt: str, journey_json: str, call_text: str,
                 schema: type[BaseModel] | None = None) -> list[dict]:
    """System = role prompt + schema. User = [journey (cacheable: identical for every call of this script
    version), call parameters + transcript (+ anything else) per call]."""
    import json

    system = prompt.replace("{schema}", json.dumps((schema or LLMJudgment).model_json_schema()))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": f"JOURNEY:\n{journey_json}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": call_text},
        ]},
    ]


def judge_llm(resolved, messages: list[dict], attempts: int = 3) -> LLMJudgment:
    return structured(resolved, messages, LLMJudgment, attempts)


def structured[T: BaseModel](resolved, messages: list[dict], model: type[T], attempts: int = 3) -> T:
    """A structured `model` via the any-llm gateway, retried on model/parse errors."""
    from voiceobs.llm import gateway

    last: Exception | None = None
    for _ in range(attempts):
        try:
            msg = gateway.complete(resolved, messages, response_format=model).choices[0].message
            parsed = getattr(msg, "parsed", None)
            if isinstance(parsed, model):
                return parsed
            data = parsed if parsed is not None else msg.content
            return model.model_validate(data) if isinstance(data, dict) else model.model_validate_json(data)
        except Exception as e:  # noqa: BLE001 — retry, then surface
            last = e
    raise RuntimeError(f"journey LLM ({model.__name__}) failed after {attempts} attempts: {last}")
