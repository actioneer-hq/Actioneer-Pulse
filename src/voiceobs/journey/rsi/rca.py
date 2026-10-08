"""Step 3 — why the agent didn't follow a script item (the decision model, fixed values).

Per not-followed failure group: the script journey + the item + call snippets -> one reason. `model`
means the script is fine and the agent just didn't follow it — fix with training data, not the script.
`situational` means it couldn't be followed in those calls — no fix. The rest are script fixes.

`wrong_place` is decided in code first, not asked: the stage where most of the failures happened (from
the timeline) differs from where the instruction is written (a guardrail / any-time situation, or another
stage's branch). The fix target is that stage. Failures spread across stages are not wrong_place.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from voiceobs.journey.jev import JevQuestion, _pick
from voiceobs.journey.model import Journey
from voiceobs.journey.rsi.common import Failure, evidence

REASONS = {
    "The instruction is vague or open to interpretation": "vague",
    "The instruction conflicts with another part of the script": "conflict",
    "The instruction is long, and the action the agent must take is hidden inside it": "too_long",
    "The stage asks the agent to do too many things at once": "overloaded",
    "The instruction is critical but stated once, with no emphasis": "not_emphasized",
    "The customer's situation made it impossible to follow": "situational",
    "The script is clear about it; the agent simply did not follow it": "model",
}
SCRIPT_FIXES = {"vague", "conflict", "too_long", "overloaded", "not_emphasized", "wrong_place"}
MAJORITY = 0.6   # share of failures in one stage for it to be "where it happens"
MIN_CALLS = 3    # fewer failures than this is too thin to move an instruction


def _written_in(j: Journey, f: Failure) -> str | None:
    """The stage an instruction is written in, or None (guardrails / any-time / opening / closing)."""
    if f.kind == "branch":
        return next((s.stage for s in j.funnel for b in s.side if b.if_ == f.item), None)
    return None


def wrong_place(j: Journey, f: Failure) -> str | None:
    """The stage the instruction belongs in, if its failures concentrate in a stage it isn't written in."""
    stages = [s for s in f.stages if s in {x.stage for x in j.funnel}]
    if f.kind in ("stage", "opening", "closing") or len(stages) < MIN_CALLS:
        return None
    top = max(set(stages), key=stages.count)
    if stages.count(top) / len(f.stages) < MAJORITY or top == _written_in(j, f):
        return None
    return top


def _question(f: Failure) -> JevQuestion:
    return JevQuestion(key="reason", kind="choice", options=list(REASONS),
                       text=f"In these calls the agent did not follow this part of the script ({f.kind}): "
                            f"'{f.item}'. Looking at the SCRIPT JOURNEY and the CALL SNIPPETS, what is the main "
                            f"reason it wasn't followed?")


def rca(j: Journey, failures: list[Failure], decision) -> list[dict]:
    script = json.dumps(j.model_dump(mode="json", by_alias=True, exclude_none=True), ensure_ascii=False)

    def one(f: Failure) -> dict:
        base = {"kind": f.kind, "item": f.item, "calls": f.calls}
        target = wrong_place(j, f)
        if target:
            return {**base, "reason": "wrong_place", "p": None, "stage": target, "fix": "script"}
        try:
            a = decision.decide(f"SCRIPT JOURNEY:\n{script}\n\n{evidence(f.windows)}", [_question(f)])
            label, p = _pick(a["reason"])
            reason, p = REASONS[label], round(p, 3)
        except Exception:  # noqa: BLE001 — an undecided failure is left out, never guessed
            reason, p = None, None
        return {**base, "reason": reason, "p": p,
                "fix": "script" if reason in SCRIPT_FIXES else "training" if reason == "model" else None}

    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(one, failures))
