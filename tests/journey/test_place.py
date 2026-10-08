"""Placement of a script-gap cluster in the journey: pass 1 (which part) and pass 2 (which item / none)."""

from __future__ import annotations

from voiceobs.journey.place import NONE, component, match_question, part_question, to_match, to_part

from .test_models import journey  # noqa: F401 — fixture


def test_pass1_options_are_each_stage_plus_the_other_parts(journey):  # noqa: F811
    q = part_question(journey)
    stages = [o for o in q.options if o.startswith("A situation during the stage")]
    assert len(stages) == 3 and "'Offer'" in stages[1]
    assert len(q.options) == 3 + 5   # + anytime, guardrail, fact, escalation, off-topic


def test_pass1_maps_to_category_and_stage(journey):  # noqa: F811
    q = part_question(journey)
    offer = next(o for o in q.options if "'Offer'" in o)
    assert to_part(journey, {"part": {offer: 0.8}}) == ("branch", "Offer", 0.8)
    guard = next(o for o in q.options if "guardrail" in o)
    assert to_part(journey, {"part": {guard: 0.6}})[:2] == ("guardrail", None)


def test_pass2_sees_only_the_chosen_part(journey):  # noqa: F811
    part, items = component(journey, "branch", "Offer")
    assert part["stage"] == "Offer" and items == ["Price too high"]
    assert component(journey, "fact", None) is None and component(journey, "off_topic", None) is None
    q = match_question(items)
    assert q.options == ["Price too high", NONE] and "same situation" in q.text


def test_pass2_maps_match_or_none():
    assert to_match({"match": {"Price too high": 0.85}}) == ("Price too high", 0.85)
    assert to_match({"match": {NONE: 0.7}}) == (None, 0.7)
