"""Where a recurring unscripted moment belongs in the script journey — two decision-model passes.

Pass 1 (`part_question`) reads the WHOLE script journey + the leaf's description + call transcripts and
picks the part of the journey that should handle it: one specific stage, the anytime situations, the
guardrails, the facts, escalation, or off-topic.
Pass 2 (`match_question`) reads ONLY that part's JSON + the description + transcripts and picks the item
that already covers it, or "None of these" (the script doesn't cover it yet). Facts and off-topic have no
pass 2: the journey holds no facts, and off-topic needs no script change.
"""

from __future__ import annotations

import json

from voiceobs.journey.jev import JevAnswers, JevQuestion, _pick
from voiceobs.journey.model import Journey

NONE = "None of these — the script doesn't cover this situation"
_ANYTIME = "A situation that can come up at any point in the call, not tied to one stage"
_GUARDRAIL = "A rule the agent must always or never follow (a guardrail)"
_FACT = "A fact the agent needs in order to answer (about the product, price, company or a process)"
_ESCALATION = "A callback request, a request for a human, or a machine answering the call (escalation)"
_OFF_TOPIC = "Off-topic chatter or noise that the script should not handle"


def _stage_option(stage) -> str:
    return f"A situation during the stage '{stage.stage}' (when the agent: {stage.agent})"


def _parts(j: Journey) -> dict[str, tuple[str, str | None]]:
    """Pass-1 option label -> (category, stage)."""
    out = {_stage_option(s): ("branch", s.stage) for s in j.funnel}
    out.update({_ANYTIME: ("anytime", None), _GUARDRAIL: ("guardrail", None), _FACT: ("fact", None),
                _ESCALATION: ("escalation", None), _OFF_TOPIC: ("off_topic", None)})
    return out


def part_question(j: Journey) -> JevQuestion:
    return JevQuestion(
        key="part", kind="choice", options=list(_parts(j)),
        text="The LEAF MOMENT is something customers raised in calls like the ones shown, which the agent "
             "had to respond to. Which part of the SCRIPT JOURNEY should tell the agent how to handle it? "
             "Choose the stage where it comes up if it belongs to one stage of the call; choose the "
             "any-point option only if it can happen anywhere.")


def to_part(j: Journey, a: JevAnswers) -> tuple[str | None, str | None, float | None]:
    """(category, stage, probability) from pass 1."""
    dist = a.get("part")
    if not isinstance(dist, dict) or not dist:
        return None, None, None
    label, p = _pick(dist)
    category, stage = _parts(j).get(label, (None, None))
    return category, stage, round(p, 3)


def component(j: Journey, category: str, stage: str | None) -> tuple[object, list[str]] | None:
    """The JSON of the chosen part and its items, for pass 2 (None = no pass 2)."""
    if category == "branch":
        s = next((s for s in j.funnel if s.stage == stage), None)
        if s is None:
            return None
        return s.model_dump(mode="json", by_alias=True), [b.if_ for b in s.side]
    if category in ("anytime", "escalation"):
        rules = [r for r in j.anytime if r.standard == (category == "escalation")]
        return [r.model_dump(mode="json", by_alias=True) for r in rules], [r.if_ for r in rules]
    if category == "guardrail":
        return [g.model_dump(mode="json", by_alias=True) for g in j.guardrails], [g.rule for g in j.guardrails]
    return None


def match_question(items: list[str]) -> JevQuestion:
    return JevQuestion(
        key="match", kind="choice", options=[*items, NONE],
        text="PART is one part of the agent's script. Which of its items already tells the agent how to "
             "handle the LEAF MOMENT? An item matches only if it is about the same situation — the same "
             "customer need, question or objection — even when worded differently. If no item is about "
             "that situation, choose None of these, even when an item is on a related topic (the same "
             "topic but a different situation is not a match).")


def to_match(a: JevAnswers) -> tuple[str | None, float | None]:
    dist = a.get("match")
    if not isinstance(dist, dict) or not dist:
        return None, None
    item, p = _pick(dist)
    return (None if item == NONE else item), round(p, 3)


def _calls(description: str, transcript_text: str, windows: list[str]) -> str:
    parts = [f"LEAF MOMENT (recurs across many calls): {description}",
             f"ONE CALL WHERE IT HAPPENED:\n{transcript_text}"]
    parts += [f"ANOTHER CALL, AROUND THE MOMENT:\n{w}" for w in windows]
    return "\n\n".join(parts)


def pass1_input(journey_json: dict, description: str, transcript_text: str, windows: list[str]) -> str:
    return f"SCRIPT JOURNEY:\n{json.dumps(journey_json, ensure_ascii=False)}\n\n" + _calls(
        description, transcript_text, windows)


def pass2_input(part_json: object, description: str, transcript_text: str, windows: list[str]) -> str:
    return f"PART:\n{json.dumps(part_json, ensure_ascii=False)}\n\n" + _calls(description, transcript_text, windows)
