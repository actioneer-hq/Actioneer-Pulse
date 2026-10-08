"""Script B (restructure) — the LLM proposes typed operations on the conversation flow; code applies them.

Operations: remove_stage, merge_stages, reorder, rewrite_stage, move_item. Each carries the evidence it
rests on (where calls stall, what isn't followed). Code validates every operation against the current
journey and applies it, so even a big restructure is an exact, trackable diff; invalid ones are rejected
with the reason. Facts, guardrails and the objective are never removed here.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from voiceobs.journey.model import END, SAME, AnytimeRule, Journey, Origin, SideBranch, Stage

TASK = """TASK: restructure the CONVERSATION FLOW to reach the objective more often. Use the evidence: STAGE REACH
(how many calls reach each stage — where calls stall), NOT FOLLOWED (script parts the agent didn't follow,
with why), and the NEW ADDITIONS. Prefer fewer, clearer stages; remove or merge stages that stall calls
without moving them toward the objective; reorder when the evidence says so; move a branch to where it
actually comes up. Return a list of operations, each with the evidence it rests on in `reason`. Only
these operations exist:
- remove_stage: stage
- merge_stages: stages (2+, in order) + new_stage (the merged stage: stage, agent, done_when, say)
- reorder: stages (every current stage, new order)
- rewrite_stage: stage + new_stage (same or new name; agent, done_when, say)
- move_item: item (a branch's `if`) + to (a stage name, or "anytime")
Do not touch facts, guardrails or the objective. Return no operations if the flow is already right."""


class NewStage(BaseModel):
    stage: str
    agent: str
    done_when: str
    say: list[str] = Field(default_factory=list)


class Op(BaseModel):
    op: Literal["remove_stage", "merge_stages", "reorder", "rewrite_stage", "move_item"]
    reason: str
    stage: str | None = None
    stages: list[str] = Field(default_factory=list)
    new_stage: NewStage | None = None
    item: str | None = None
    to: str | None = None


class Plan(BaseModel):
    ops: list[Op] = Field(default_factory=list)


def plan_input(j: Journey, reach: list[dict], findings: list[dict], additions: list[dict]) -> str:
    return "\n\n".join([
        f"SCRIPT JOURNEY:\n{json.dumps(j.model_dump(mode='json', by_alias=True, exclude_none=True), ensure_ascii=False)}",
        "STAGE REACH: " + ", ".join(f"{r['stage']} {r['reached']}" for r in reach),
        "NOT FOLLOWED:\n" + "\n".join(f"- {f['kind']} '{f['item']}' in {f['calls']} calls (why: {f['reason']})"
                                      for f in findings if f.get("reason")),
        "NEW ADDITIONS:\n" + "\n".join(f"- {a['section']}: {a['id']}" for a in additions)])


def _retarget(j: Journey, old: set[str], new: str) -> None:
    for _, b in j.branches():
        if b.goes_to in old:
            b.goes_to = new


def apply(j: Journey, plan: Plan, run: str) -> tuple[Journey, list[dict]]:
    """Apply valid operations in order. Returns the new journey and a log of applied / rejected ops."""
    j = j.model_copy(deep=True)
    log = []
    for op in plan.ops:
        before = j.model_copy(deep=True)
        names = [s.stage for s in j.funnel]
        origin = Origin(change="revised", run=run, reason=op.reason, source=[op.op])
        err = None
        if op.op == "remove_stage":
            if op.stage not in names or len(names) == 1:
                err = "unknown stage, or it is the only stage"
            else:
                i = names.index(op.stage)
                gone = j.funnel.pop(i)
                nxt = j.funnel[i].stage if i < len(j.funnel) else END
                _retarget(j, {gone.stage}, nxt)
                for b in gone.side:  # its handling stays: the situations become any-time ones
                    if all(r.if_ != b.if_ for r in j.anytime):
                        j.anytime.insert(0, AnytimeRule(**{**b.model_dump(by_alias=True), "goes_to":
                                                           b.goes_to if b.goes_to != gone.stage else SAME}))
        elif op.op == "merge_stages":
            if len(op.stages) < 2 or not set(op.stages) <= set(names) or op.new_stage is None:
                err = "needs 2+ existing stages and new_stage"
            else:
                parts = [s for s in j.funnel if s.stage in op.stages]
                merged = Stage(**op.new_stage.model_dump(), side=[b for s in parts for b in s.side], origin=origin)
                at = names.index(op.stages[0])
                j.funnel = [s for s in j.funnel if s.stage not in op.stages]
                j.funnel.insert(min(at, len(j.funnel)), merged)
                _retarget(j, set(op.stages), merged.stage)
        elif op.op == "reorder":
            if sorted(op.stages) != sorted(names):
                err = "must list every current stage exactly once"
            else:
                j.funnel = sorted(j.funnel, key=lambda s: op.stages.index(s.stage))
        elif op.op == "rewrite_stage":
            if op.stage not in names or op.new_stage is None:
                err = "unknown stage or no new_stage"
            else:
                i = names.index(op.stage)
                j.funnel[i] = Stage(**op.new_stage.model_dump(), side=j.funnel[i].side, origin=origin)
                _retarget(j, {op.stage}, op.new_stage.stage)
        elif op.op == "move_item":
            src = next(((s.side, b) for s in j.funnel for b in s.side if b.if_ == op.item), None) or next(
                ((j.anytime, r) for r in j.anytime if r.if_ == op.item and not r.standard), None)
            if src is None or (op.to != "anytime" and op.to not in names):
                err = "unknown item or destination"
            else:
                src[0].remove(src[1])
                data = {**src[1].model_dump(by_alias=True, exclude={"standard", "in_script"}), "origin": origin.model_dump()}
                if op.to == "anytime":
                    j.anytime.insert(0, AnytimeRule(**data))
                else:
                    next(s for s in j.funnel if s.stage == op.to).side.append(SideBranch(**data))
        entry = op.model_dump(exclude_none=True)
        if err is None:
            try:
                j = Journey.model_validate(j.model_dump(by_alias=True))
            except Exception as e:  # noqa: BLE001 — an op that breaks the journey is rejected
                err = f"invalid result: {e}"[:200]
        if err is not None:
            j = before
        log.append({**entry, "applied": err is None, **({"rejected": err} if err else {})})
    return Journey.model_validate(j.model_dump(by_alias=True)), log
