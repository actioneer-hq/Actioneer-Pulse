"""Script A (conservative) — revise only the script items the agent didn't follow.

Failures with a script fix are grouped by their item; one LLM call per item gets the item's JSON, its
failures, their RCA reasons and call snippets, and returns the revised item (same shape). Code swaps it in
with `origin` (revised). Only `not_emphasized` adds a guardrail.
`wrong_place` is fixed where the failures happen: a situation (any-time, or another stage's branch) is
moved into that stage in code; a rule is written into that stage's instructions by the LLM.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from voiceobs.journey.model import Guardrail, Journey, Origin, SideBranch, Stage
from voiceobs.journey.rsi.common import LLM, Failure, evidence

log = logging.getLogger(__name__)

FIXES = {
    "vague": "make it concrete and checkable: say exactly what the agent says or does, and when",
    "conflict": "resolve the conflict with the other part of the script it clashes with (keep the stricter intent)",
    "too_long": "rewrite it as a short, separate instruction that leads with the action the agent must take",
    "overloaded": "keep one clear goal for this item; drop or move secondary goals so the agent isn't juggling",
    "not_emphasized": "make it explicit and firm here, and also give a one-line guardrail for it",
}
TASK = """TASK: in real calls the agent did not follow this ITEM of the script. For each REASON listed, apply its
FIX. Return the revised item in the same shape (keep its id — the stage name / the branch `if` / the rule
text — unless the fix needs rewording), keeping its intent, facts and language."""


class Revised(BaseModel):
    """Base of the typed revision outputs (a free-form dict lets the model return nothing)."""

    guardrail: str | None = Field(default=None, description="only for not_emphasized: a one-line rule")

    @property
    def item(self) -> dict:
        return self.model_dump(by_alias=True, exclude={"guardrail"}, exclude_none=True)


class RevisedStage(Revised):
    agent: str = Field(description="what the agent does at this stage")
    done_when: str = Field(description="what shows in a transcript that the stage is complete")
    say: list[str] = Field(default_factory=list, description="1-2 short sample lines")


class RevisedBranch(Revised):
    model_config = ConfigDict(populate_by_name=True)

    if_: str = Field(alias="if", description="the customer's situation")
    then: str = Field(description="what the agent should do")
    goes_to: str = Field(description="a stage name, 'Same stage' or 'End'")
    say: list[str] = Field(default_factory=list)


class RevisedGuardrail(Revised):
    rule: str


class RevisedBookend(Revised):
    agent: str
    done_when: str
    say: list[str] = Field(default_factory=list)


def _schema(cur) -> type[Revised]:
    if isinstance(cur, Stage):
        return RevisedStage
    if isinstance(cur, Guardrail):
        return RevisedGuardrail
    if isinstance(cur, SideBranch):
        return RevisedBranch
    return RevisedBookend


def _locate(j: Journey, kind: str, name: str):
    """(container list or owner, index or attr, current item) for a failure's item."""
    if kind == "stage":
        return next(((j.funnel, i, s) for i, s in enumerate(j.funnel) if s.stage == name), None)
    if kind in ("opening", "closing"):
        b = getattr(j, kind)
        return (j, kind, b) if b else None
    if kind == "guardrail":
        return next(((j.guardrails, i, g) for i, g in enumerate(j.guardrails) if g.rule == name), None)
    for s in j.funnel:
        for i, b in enumerate(s.side):
            if b.if_ == name:
                return s.side, i, b
    return next(((j.anytime, i, r) for i, r in enumerate(j.anytime) if r.if_ == name), None)


PLACE_TASK = """TASK: in real calls the agent kept breaking the RULES below during this STAGE, because they are
written elsewhere in the script. Return the STAGE with each rule written into its `agent` instructions as
a short, direct line (keep the stage name, its goal, done_when and say)."""


def _move_into_stage(j: Journey, item: str, stage: str, origin: Origin) -> bool:
    """Move a situation (any-time, or another stage's branch) into `stage`. False if not movable."""
    target = next((s for s in j.funnel if s.stage == stage), None)
    src = next(((s.side, b) for s in j.funnel for b in s.side if b.if_ == item), None) or next(
        ((j.anytime, r) for r in j.anytime if r.if_ == item and not r.standard), None)
    if target is None or src is None:
        return False
    src[0].remove(src[1])
    data = src[1].model_dump(by_alias=True, exclude={"standard", "in_script", "origin"})
    target.side.append(SideBranch(**{**data, "origin": origin.model_dump()}))
    return True


def _place_rules(j: Journey, stage: str, rs: list[dict], llm: LLM, run: str) -> None:
    i = next((n for n, s in enumerate(j.funnel) if s.stage == stage), None)
    if i is None:
        return
    cur = j.funnel[i]
    text = (f"STAGE: {json.dumps(cur.model_dump(mode='json', exclude={'origin', 'side'}), ensure_ascii=False)}\n\n"
            "RULES:\n" + "\n".join(f"- {r['item']} (broken in {r['calls']} calls)" for r in rs))
    out = llm(PLACE_TASK, text, RevisedStage)
    origin = Origin(change="revised", run=run, reason="rules broken during this stage written into it: "
                    + "; ".join(r["item"] for r in rs), source=[f"{r['kind']}:{r['item']}" for r in rs])
    data = {**cur.model_dump(by_alias=True), **{k: v for k, v in out.item.items() if k not in ("side", "origin")}}
    try:
        j.funnel[i] = Stage.model_validate({**data, "stage": cur.stage, "origin": origin.model_dump()})
    except Exception:  # noqa: BLE001 — a malformed rewrite is skipped, the stage stays as it was
        log.warning("script A: discarded a malformed rewrite of stage '%s'", stage)


def revise(j: Journey, findings: list[dict], failures: list[Failure], llm: LLM, run: str) -> Journey:
    j = j.model_copy(deep=True)
    windows = {(f.kind, f.item): f.windows for f in failures}
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    rules_by_stage: dict[str, list[dict]] = defaultdict(list)
    for r in findings:
        if r["fix"] != "script":
            continue
        if r["reason"] == "wrong_place":
            origin = Origin(change="moved", run=run, reason=f"broken in {r['calls']} calls during '{r['stage']}', "
                            f"where it wasn't written", source=[f"{r['kind']}:{r['item']}"])
            if r["kind"] in ("branch", "standard") and _move_into_stage(j, r["item"], r["stage"], origin):
                continue
            rules_by_stage[r["stage"]].append(r)
            continue
        by[("branch" if r["kind"] == "standard" else r["kind"], r["item"])].append(r)
    for stage, rs in rules_by_stage.items():
        _place_rules(j, stage, rs, llm, run)
    for (kind, name), rs in by.items():
        found = _locate(j, kind, name)
        if not found:
            continue
        where, at, cur = found
        reasons = sorted({r["reason"] for r in rs})
        text = "\n\n".join([
            f"ITEM ({kind}): {json.dumps(cur.model_dump(mode='json', by_alias=True, exclude={'origin', 'side'}), ensure_ascii=False)}",
            "REASONS AND FIXES:\n" + "\n".join(f"- {x}: {FIXES[x]}" for x in reasons),
            evidence([w for r in rs for w in windows.get((r["kind"], r["item"]), [])])])
        out = llm(TASK, text, _schema(cur))
        origin = Origin(change="revised", run=run, reason=f"not followed in {sum(r['calls'] for r in rs)} calls "
                        f"({', '.join(reasons)})", source=[f"{kind}:{name}"])
        cls = type(cur)
        data = {**cur.model_dump(by_alias=True), **{k: v for k, v in out.item.items() if k not in ("side", "origin")}}
        try:
            new = cls.model_validate({**data, "origin": origin.model_dump()})
        except Exception:  # noqa: BLE001 — a malformed revision is skipped, the item stays as it was
            log.warning("script A: discarded a malformed revision of %s '%s'", kind, name)
            continue
        if isinstance(where, Journey):
            setattr(where, at, new)
        else:
            where[at] = new
        if "not_emphasized" in reasons and out.guardrail and all(g.rule != out.guardrail for g in j.guardrails):
            j.guardrails.append(Guardrail(rule=out.guardrail, origin=origin))
    return Journey.model_validate(j.model_dump(by_alias=True))

