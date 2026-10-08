"""Keep the rendered script under the limit: shorten only sample lines and fact wording (never drop an
item), then re-render. Up to two passes."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from voiceobs.journey.model import Journey
from voiceobs.journey.rsi.common import LLM
from voiceobs.journey.rsi.render import LIMIT, render

TASK = """TASK: the script is {over} characters over its {limit}-character limit. Shorten the FACTS texts and the
SAY lines so the total shrinks by at least that much. Keep every number, name, price and step in the
facts; keep each say line's meaning and language. Return every entry with its id, shortened."""


class Entry(BaseModel):
    id: str
    text: str


class Shortened(BaseModel):
    facts: list[Entry] = Field(default_factory=list)
    say: list[Entry] = Field(default_factory=list)


def _says(j: Journey) -> dict[str, object]:
    """id -> the object whose `say` it is."""
    out: dict[str, object] = {}
    for key in ("opening", "closing"):
        if getattr(j, key):
            out[key] = getattr(j, key)
    for s in j.funnel:
        out[f"stage:{s.stage}"] = s
        for b in s.side:
            out[f"branch:{b.if_}"] = b
    for r in j.anytime:
        out[f"anytime:{r.if_}"] = r
    return {k: v for k, v in out.items() if getattr(v, "say", None)}


def fit(j: Journey, llm: LLM, limit: int = LIMIT) -> Journey:
    j = j.model_copy(deep=True)
    for _ in range(2):
        over = len(render(j)) - limit
        if over <= 0:
            break
        says = _says(j)
        text = json.dumps({"facts": [{"id": f.topic, "text": f.text} for f in j.facts],
                           "say": [{"id": k, "text": " || ".join(v.say)} for k, v in says.items()]}, ensure_ascii=False)
        out = llm(TASK.format(over=over, limit=limit), text, Shortened)
        facts = {e.id: e.text for e in out.facts}
        for f in j.facts:
            if facts.get(f.topic):
                f.text = facts[f.topic]
        for e in out.say:
            if e.id in says and e.text.strip():
                says[e.id].say = [x.strip() for x in e.text.split("||") if x.strip()][:2]
    return j
