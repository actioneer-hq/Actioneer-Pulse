"""Decision-model client: send a call's text + our questions, get numbers back (JevAnswers).

Behind one protocol so the provider is swappable: OpenAI's Decisions API (`gpt-6-luna`) today, TypeSafe
Jev later. Questions are split into requests of at most 200 (the API's limit) and the requests are sent
in parallel; answers are mapped back to our question keys.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import httpx

from voiceobs.journey.jev import JevAnswers, JevQuestion

log = logging.getLogger(__name__)

MAX_QUESTIONS = 200
_SCORE_LEVELS = ["very negative", "negative", "neutral", "positive", "very positive"]


class DecisionModel(Protocol):
    name: str

    def decide(self, text: str, questions: list[JevQuestion]) -> JevAnswers: ...


class DecisionError(RuntimeError):
    pass


def _to_api(questions: list[JevQuestion], offset: int) -> list[dict]:
    out = []
    for i, q in enumerate(questions, start=offset):
        if q.kind == "yes_no":
            out.append({"type": "predicate", "name": f"q{i}", "instructions": q.text})
        elif q.kind == "choice":
            out.append({"type": "choice", "name": f"q{i}", "instructions": q.text,
                        "choices": [{"value": f"o{k}", "description": o}
                                    for k, o in enumerate(q.options or [])]})
        else:
            out.append({"type": "score", "name": f"q{i}", "instructions": q.text,
                        "levels": [{"label": lv, "description": lv} for lv in _SCORE_LEVELS]})
    return out


def _from_api(questions: list[JevQuestion], answers: list[dict]) -> JevAnswers:
    by = {a.get("name"): a for a in answers}
    res: JevAnswers = {}
    for i, q in enumerate(questions):
        a = by.get(f"q{i}")
        if not a or a.get("type") == "refusal":
            continue
        if q.kind == "yes_no":
            res[q.key] = float(a.get("probability") or 0.0)
        elif q.kind == "choice":
            opts = q.options or []
            dist = {opts[int(p["value"][1:])]: float(p["probability"])
                    for p in a.get("probabilities") or [] if str(p.get("value", "")).startswith("o")}
            if not dist and a.get("choice"):
                dist = {opts[int(a["choice"][1:])]: float(a.get("confidence") or 1.0)}
            res[q.key] = dist
        else:  # score: position on the 5 levels (0..4) -> our scale
            lo, hi = q.scale or (-2.0, 2.0)
            res[q.key] = lo + float(a.get("score") or 2.0) / (len(_SCORE_LEVELS) - 1) * (hi - lo)
    return res


class OpenAIDecisions:
    """OpenAI Decisions API (`POST /v1/decisions`)."""

    def __init__(self, api_key: str, model: str = "gpt-6-luna",
                 base_url: str = "https://api.openai.com/v1", timeout: float = 120.0):
        self.name = f"openai:{model}"
        self._key, self._model, self._url, self._timeout = api_key, model, f"{base_url}/decisions", timeout

    def _post(self, text: str, api_questions: list[dict], tries: int = 4) -> list[dict]:
        for i in range(tries):
            r = httpx.post(self._url, timeout=self._timeout,
                           headers={"Authorization": f"Bearer {self._key}"},
                           json={"model": self._model, "input": text, "questions": api_questions})
            if r.status_code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 ** i)
                continue
            if r.status_code >= 400:
                raise DecisionError(f"decisions API {r.status_code}: {r.text[:300]}")
            return r.json().get("answers") or []
        raise DecisionError("decisions API: retries exhausted")

    def decide(self, text: str, questions: list[JevQuestion]) -> JevAnswers:
        chunks = [(i, questions[i: i + MAX_QUESTIONS]) for i in range(0, len(questions), MAX_QUESTIONS)]
        with ThreadPoolExecutor(max(1, len(chunks))) as pool:
            parts = list(pool.map(lambda c: self._post(text, _to_api(c[1], c[0])), chunks))
        return _from_api(questions, [a for part in parts for a in part])


def resolve_decision() -> DecisionModel | None:
    """The configured decision model, or None (journey judging then falls back to the classic judge)."""
    from voiceobs.config import get_config

    cfg = get_config()
    if not cfg.decision_api_key:
        return None
    if cfg.decision_provider == "openai":
        return OpenAIDecisions(cfg.decision_api_key, cfg.decision_model)
    raise ValueError(f"unknown decision provider: {cfg.decision_provider}")


def render_input(params: dict | None, transcript: dict, script: str | None = None) -> str:
    """What a judge reads: the call's parameters + the turn-indexed transcript, after the agent's script
    when given. The decision model gets the script: its questions carry only one line per rule, and a
    rule read without the script's facts and exceptions (prices, allowed discounts, one rebuttal) gets
    flagged on calls that followed the script."""
    import json

    head = f"THE AGENT'S SCRIPT (what it was told to do):\n{script}\n\n" if script else ""
    head += f"CALL PARAMETERS: {json.dumps(params or {}, ensure_ascii=False)}\n\nTRANSCRIPT:\n"
    lines = transcript.get("lines")
    if lines:
        return head + "\n".join(
            f"[{ln.get('turn_index', '?')}] {'customer' if ln.get('role') == 'caller' else 'agent'}: "
            f"{ln.get('text', '')}" for ln in lines)
    return head + (transcript.get("text") or "(empty)")
