"""Step 1 — add every script gap (unscripted leaf placed as "none of these") as a new journey item.

One LLM call per gap writes ONE item of the gap's category, from the gap's description and call evidence
(replies that worked = the basis, failed ones = what to avoid), the target part and the facts. Every
addition carries `origin` (added, run, reason, source) — the diff. Off-topic gaps are skipped.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from voiceobs.journey.model import AnytimeRule, Fact, Guardrail, Journey, Origin, SideBranch
from voiceobs.journey.rsi.common import LLM, Gap, evidence, insert_anytime, valid_goto

TASK = """TASK: real calls keep hitting a situation the script doesn't cover (the GAP). Write ONE new {what} for
the script that handles it. Handle the underlying need so it also covers similar situations. Use the
CALL SNIPPETS as evidence: copy what worked, avoid what didn't. `say`: 1-2 short sample lines in the
script's language. Only use facts that appear in the script's FACTS; if the answer needs a fact the
script doesn't have, write the handling without it and set needs_input."""


class NewBranch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    if_: str = Field(alias="if", description="the customer's situation, in plain words")
    then: str = Field(description="what the agent should do")
    goes_to: str = Field(description="a stage name, 'Same stage' or 'End'")
    say: list[str] = Field(default_factory=list)
    needs_input: bool = False


class NewGuardrail(BaseModel):
    rule: str = Field(description="a short imperative rule a single agent line can break")


class NewFact(BaseModel):
    topic: str
    text: str = Field(description="the fact, or what the business must supply if unknown")
    needs_input: bool = False


_WHAT = {"branch": ("branch of the stage '{stage}'", NewBranch), "anytime": ("situation that can come up any time", NewBranch),
         "escalation": ("escalation situation", NewBranch), "guardrail": ("guardrail", NewGuardrail),
         "fact": ("fact", NewFact)}


def _context(j: Journey, g: Gap) -> str:
    if g.category == "branch":
        part = next((s for s in j.funnel if s.stage == g.stage), None)
        part_json = part.model_dump(mode="json", by_alias=True) if part else None
    elif g.category == "guardrail":
        part_json = [x.rule for x in j.guardrails]
    elif g.category == "fact":
        part_json = None
    else:
        part_json = [r.model_dump(mode="json", by_alias=True) for r in j.anytime]
    return "\n\n".join([
        f"OBJECTIVE: {j.objective}", f"STAGES: {[s.stage for s in j.funnel]}",
        f"FACTS: {json.dumps([f.model_dump(mode='json', exclude={'origin'}) for f in j.facts], ensure_ascii=False)}",
        *( [f"TARGET PART: {json.dumps(part_json, ensure_ascii=False)}"] if part_json is not None else [] ),
        f"GAP (seen in {g.calls} calls): {g.description}", evidence(g.windows, g.worked)])


def add_gaps(j: Journey, gaps: list[Gap], llm: LLM, run: str) -> Journey:
    j = j.model_copy(deep=True)
    for g in gaps:
        if g.category not in _WHAT:
            continue  # off-topic
        what, schema = _WHAT[g.category]
        out = llm(TASK.format(what=what.format(stage=g.stage)), _context(j, g), schema)
        origin = Origin(change="added", run=run, reason=f"not covered by the script; seen in {g.calls} calls: "
                        f"{g.description}", source=[g.id])
        if isinstance(out, NewGuardrail):
            if all(x.rule != out.rule for x in j.guardrails):
                j.guardrails.append(Guardrail(rule=out.rule, origin=origin))
        elif isinstance(out, NewFact):
            if all(f.topic != out.topic for f in j.facts):
                j.facts.append(Fact(topic=out.topic, text=out.text, needs_input=out.needs_input, origin=origin))
        else:
            fields = {"if": out.if_, "then": out.then, "goes_to": valid_goto(j, out.goes_to), "say": out.say[:2],
                      "origin": origin}
            stage = next((s for s in j.funnel if s.stage == g.stage), None)
            if g.category == "branch" and stage is not None:
                if all(b.if_ != out.if_ for b in stage.side):
                    stage.side.append(SideBranch(**fields))
            elif all(r.if_ != out.if_ for r in j.anytime):
                insert_anytime(j, AnytimeRule(**fields))
    return Journey.model_validate(j.model_dump(by_alias=True))
