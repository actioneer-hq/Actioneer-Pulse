"""Step 2 — club the new additions of each script section into meta / fundamental rules.

Per section (each stage's branches, the any-time situations, the guardrails, the facts), every pair of
items ADDED in this run is put to the decision model in one request: "same underlying principle?"
(yes/no). Pairs at >= 0.5 link; each linked group of 2+ items is rewritten by the LLM as ONE item that
states the principle, and code swaps the group for it. Section boundaries are kept: a guardrail never
merges with a stage branch.
"""

from __future__ import annotations

import json
from itertools import combinations

from voiceobs.journey.jev import THRESHOLD, JevQuestion
from voiceobs.journey.model import AnytimeRule, Fact, Guardrail, Journey, Origin, SideBranch
from voiceobs.journey.rsi.additions import NewBranch, NewFact, NewGuardrail
from voiceobs.journey.rsi.common import LLM, insert_anytime, valid_goto

TASK = """TASK: these ITEMS were added to the same section of the script separately, but they are instances of
one underlying principle. Write ONE item that states that principle at a fundamental level, so the agent
handles all of them and similar situations it hasn't met yet. Keep it concrete enough to act on, keep
every fact they use, and keep `say` to 1-2 short lines in the script's language."""


def _new(item, run: str) -> bool:
    o = getattr(item, "origin", None)
    return bool(o and o.run == run and o.change == "added")


def _text(item) -> str:
    if isinstance(item, Guardrail):
        return item.rule
    if isinstance(item, Fact):
        return f"{item.topic}: {item.text}"
    return f"If {item.if_} → {item.then}"


def groups(items: list, decision, section: str) -> list[list[int]]:
    """Linked groups (2+) among `items`, from pairwise yes/no answers."""
    pairs = list(combinations(range(len(items)), 2))
    if not pairs:
        return []
    qs = [JevQuestion(key=f"pair:{a}:{b}", kind="yes_no",
                      text=f"In the {section} of the script, item A and item B are two instances of the same "
                           f"underlying principle for how the agent should behave (not just the same topic). "
                           f"A: {_text(items[a])} | B: {_text(items[b])}") for a, b in pairs]
    answers = decision.decide(f"SCRIPT SECTION: {section}\nITEMS:\n" + "\n".join(
        f"- {_text(x)}" for x in items), qs)
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        if float(answers.get(f"pair:{a}:{b}", 0.0)) >= THRESHOLD:
            parent[find(a)] = find(b)
    by: dict[int, list[int]] = {}
    for i in range(len(items)):
        by.setdefault(find(i), []).append(i)
    return [g for g in by.values() if len(g) > 1]


def _merge(items: list, g: list[int], llm: LLM, run: str, section: str):
    members = [items[i] for i in g]
    schema = NewGuardrail if isinstance(members[0], Guardrail) else NewFact if isinstance(members[0], Fact) else NewBranch
    out = llm(TASK, f"SECTION: {section}\nITEMS:\n" + json.dumps(
        [m.model_dump(mode="json", by_alias=True, exclude={"origin"}) for m in members], ensure_ascii=False), schema)
    origin = Origin(change="merged", run=run, reason="one principle for: " + "; ".join(_text(m) for m in members),
                    source=[s for m in members for s in (m.origin.source if m.origin else [])])
    return out, origin


def club(j: Journey, decision, llm: LLM, run: str) -> Journey:
    j = j.model_copy(deep=True)
    sections = [(f"stage '{s.stage}' branches", s.side) for s in j.funnel]
    sections += [("any-time situations", j.anytime), ("guardrails", j.guardrails), ("facts", j.facts)]
    for section, items in sections:
        new = [x for x in items if _new(x, run)]
        for g in groups(new, decision, section):
            out, origin = _merge(new, g, llm, run, section)
            gone = {id(new[i]) for i in g}
            at = min(n for n, x in enumerate(items) if id(x) in gone)
            items[:] = [x for x in items if id(x) not in gone]
            if isinstance(out, NewGuardrail):
                items.insert(at, Guardrail(rule=out.rule, origin=origin))
            elif isinstance(out, NewFact):
                items.insert(at, Fact(topic=out.topic, text=out.text, needs_input=out.needs_input, origin=origin))
            else:
                cls = AnytimeRule if items is j.anytime else SideBranch
                item = cls(**{"if": out.if_}, then=out.then, goes_to=valid_goto(j, out.goes_to), say=out.say[:2],
                           origin=origin)
                if cls is AnytimeRule:
                    insert_anytime(j, item)
                else:
                    items.insert(at, item)
    return Journey.model_validate(j.model_dump(by_alias=True))
