"""Journey stage 3 — training data: rewrite each failed agent turn as what it should have said.

Input: the failures stage 1 found (decision model) with the spans stage 2 gave them (timeline), only
`not_followed` ones — script gaps are fixed in the script, not with training data. Failures are grouped
by the agent turn they happened at: one LLM call per call returns ONE correction (or `skip`) per turn,
fixing all of that turn's failures together — one right answer per moment. Cheap code filters drop non-corrections; the rest become
training samples (stored by judge/journey_stages.py in `training_sample`, read by the SFT/DPO export).
"""

from __future__ import annotations

import difflib
import logging
import re

from pydantic import BaseModel, Field

from voiceobs.journey.decide import render_input
from voiceobs.journey.llm import llm_messages, structured
from voiceobs.journey.merge import CallJudgment, journey_items
from voiceobs.journey.model import Journey
from voiceobs.journey.spans import Failure
from voiceobs.judge.failure_schema import LLMFaultKind

log = logging.getLogger(__name__)

_SAME = 0.9  # a "correction" this similar to what the agent said isn't one
MAX_PER_CALL = 8  # turns corrected per call (one LLM call; the earliest first)
_INSTRUCTION = re.compile(r"^\s*(\[.*\]|\(.*\)|(do not|don't|never|avoid|instead|the agent should)\b)",
                          re.IGNORECASE | re.DOTALL)


class Correction(BaseModel):
    id: int
    skip: bool = False
    kind: LLMFaultKind = LLMFaultKind.RESPONSE
    corrected: str | None = None
    corrected_tool: str | None = None
    corrected_args: dict | None = None
    rationale: str | None = None


class Curation(BaseModel):
    corrections: list[Correction] = Field(default_factory=list)


def targets(cj: CallJudgment) -> list[tuple[int, list[Failure]]]:
    """The agent turns worth correcting, each with its failures (not followed, deduped by item)."""
    by: dict[int, list[Failure]] = {}
    for f in cj.failures:
        if f.cause == "not_followed" and f.target_turn is not None:
            fs = by.setdefault(f.target_turn, [])
            if all(x.item != f.item for x in fs):
                fs.append(f)
    return sorted(by.items())[:MAX_PER_CALL]


def agent_text(lines: list[dict], turn: int) -> str:
    return " ".join(ln.get("text") or "" for ln in lines
                    if ln.get("turn_index") == turn and ln.get("role") != "caller").strip()


def _expected(j: Journey, f: Failure) -> str:
    if f.kind == "opening" and j.opening:
        return f"Opening: {j.opening.agent}"
    if f.kind == "closing" and j.closing:
        return f"Closing: {j.closing.agent}"
    return journey_items(j).get(f.item) or f.item


def failures_block(j: Journey, turns: list[tuple[int, list[Failure]]], lines: list[dict]) -> str:
    rows = []
    for i, (turn, fs) in enumerate(turns):
        what = "\n".join(f"  - {f.kind} '{f.item}'. The script says: {_expected(j, f)}" for f in fs)
        rows.append(f"- id {i}: the agent's turn [{turn}]: {agent_text(lines, turn)}\n  It failed:\n{what}")
    return "FAILURES (one rewrite per id, fixing everything listed under it):\n" + "\n".join(rows)


def keep(observed: str, c: Correction) -> bool:
    """Code-only filters: a real, speakable correction that differs from what was said."""
    if c.skip:
        return False
    if c.corrected_tool:
        return True
    text = (c.corrected or "").strip()
    if not text or _INSTRUCTION.match(text):
        return False
    return difflib.SequenceMatcher(None, observed.strip(), text).ratio() < _SAME


def needs_curation(cj: CallJudgment) -> bool:
    return bool(targets(cj))


def curate(resolved, journey_json: str, journey: Journey, cj: CallJudgment, params: dict | None,
           transcript: dict) -> list[dict]:
    """One LLM call -> the kept corrections as training-sample fields. Raises if the LLM call fails."""
    turns, lines = targets(cj), transcript.get("lines") or []
    if not turns:
        return []
    text = render_input(params, transcript) + "\n\n" + failures_block(journey, turns, lines)
    out = structured(resolved, llm_messages(resolved.prompt, journey_json, text, schema=Curation), Curation)
    samples = []
    for c in out.corrections:
        if not 0 <= c.id < len(turns):
            continue
        turn, fs = turns[c.id]
        observed = agent_text(lines, turn)
        if observed and keep(observed, c):
            samples.append({"turn": turn, "item": " | ".join(f.item for f in fs),
                            "failure_kind": fs[0].kind if len(fs) == 1 else "multiple",
                            "kind": c.kind.value, "observed": observed,
                            "corrected": (c.corrected or "").strip(), "corrected_tool": c.corrected_tool,
                            "corrected_args": c.corrected_args, "rationale": c.rationale})
    return samples
