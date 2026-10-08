"""Script journey JSON -> the agent's script text (Markdown). Pure, deterministic: same JSON, same text.

Layout (voice-agent prompting guidance: Markdown sections, short bullets, sample lines, a dedicated
guardrails section, reference data wrapped in <facts>):
# Role & Objective / # Personality & Tone / # Facts / # Conversation Flow (## Opening, ## Stage N — …,
## Closing) / # Situations Any Time / # Guardrails / # Escalation
"""

from __future__ import annotations

from voiceobs.journey.model import END, SAME, Bookend, Journey, SideBranch, Stage

LIMIT = 15_000


def _say(lines: list[str]) -> list[str]:
    return [f'- Say: "{line}"' for line in lines[:2]]


def _then(b: SideBranch) -> str:
    if b.goes_to == SAME:
        return b.then
    if b.goes_to == END:
        return f"{b.then} Then end the call."
    return f"{b.then} Then go to {b.goes_to}."


def _branch(b: SideBranch) -> list[str]:
    out = [f"- If {b.if_} → {_then(b)}"]
    out += [f'  - Say: "{line}"' for line in b.say[:1]]
    return out


def _bookend(title: str, b: Bookend) -> list[str]:
    return [f"## {title}", f"- Do: {b.agent}", *_say(b.say), f"- Done when: {b.done_when}", ""]


def _stage(n: int, s: Stage) -> list[str]:
    out = [f"## Stage {n} — {s.stage}", f"- Goal: {s.agent}", *_say(s.say)]
    for b in s.side:
        out += _branch(b)
    return [*out, f"- Move on when: {s.done_when}", ""]


def render(j: Journey) -> str:
    p = j.persona
    lines = ["# Role & Objective"]
    if p and (p.name or p.company):
        who = " from ".join(x for x in (p.name, p.company) if x)
        lines.append(f"- You are {who}.")
    lines += [f"- Objective: {j.objective}", ""]
    if p and (p.tone or p.language):
        lines += ["# Personality & Tone", *[f"- {t}" for t in p.tone], *[f"- {t}" for t in p.language], ""]
    if j.facts:
        lines += ["# Facts", "<facts>"]
        for f in j.facts:
            note = " (TO CONFIRM — supplied by the business)" if f.needs_input else ""
            lines += [f"{f.topic}{note}:", f.text.strip()]
        lines += ["</facts>", ""]
    lines += ["# Conversation Flow", ""]
    if j.opening:
        lines += _bookend("Opening", j.opening)
    for n, s in enumerate(j.funnel, 1):
        lines += _stage(n, s)
    if j.closing:
        lines += _bookend("Closing", j.closing)
    situations = [r for r in j.anytime if not r.standard]
    if situations:
        lines += ["# Situations Any Time", *[x for r in situations for x in _branch(r)], ""]
    if j.guardrails:
        lines += ["# Guardrails", *[f"- {g.rule}" for g in j.guardrails], ""]
    escalation = [r for r in j.anytime if r.standard]
    if escalation:
        lines += ["# Escalation", *[x for r in escalation for x in _branch(r)], ""]
    return "\n".join(lines).strip() + "\n"
