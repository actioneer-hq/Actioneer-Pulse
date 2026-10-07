"""Journey models: validation, building from a draft, Jev questions/mapping, and the merge."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from voiceobs.journey.build import STANDARD_RULES, build_journey
from voiceobs.journey.jev import COMPLETED, jev_questions, to_judgment
from voiceobs.journey.llm import LLMJudgment
from voiceobs.journey.merge import merge
from voiceobs.journey.model import Journey, JourneyDraft
from voiceobs.judge.schema import AnsweredBy, Objective, Sentiment

SCRIPT = (
    "Greet {{customer_name}} and introduce yourself. Tell them their plan costs {{amount}}. "
    "If they say it is too expensive, explain the monthly cost. "
    "If they are busy, ask when to call back and end. "
    "Never promise guaranteed returns. "
    "Guide them through payment step by step."
)

DRAFT = {
    "objective": "Customer pays on the call",
    "funnel": [
        {"stage": "Opening", "agent": "Greet and introduce", "done_when": "Customer responds",
         "script_quote": "Greet {{customer_name}} and introduce yourself.",
         "side": [{"if": "Customer is busy", "then": "Ask when to call back, end", "goes_to": "End",
                   "script_quote": "If they are busy, ask when to call back and end."}]},
        {"stage": "Offer", "agent": "State the price", "done_when": "Price stated",
         "side": [
             {"if": "Price too high", "then": "Explain the monthly cost", "goes_to": "Same stage",
              "script_quote": "If they say it is too expensive, explain the monthly cost."},
             {"if": "Asks for a discount", "then": "Offer 50% off", "goes_to": "Payment",
              "script_quote": "Give a 50% discount when asked."},  # not in the script -> dropped
         ]},
        {"stage": "Payment", "agent": "Guide payment", "done_when": "Payment completed"},
    ],
    "guardrails": [{"rule": "Never promise guaranteed returns",
                    "script_quote": "Never promise guaranteed returns."},
                   {"rule": "Always say please", "script_quote": "Say please every turn."}],
    "standard_coverage": {"callback": "If they are busy, ask when to call back and end.",
                          "escalation": "Transfer to a human when asked."},  # not in script
}


@pytest.fixture
def journey() -> Journey:
    return build_journey(SCRIPT, JourneyDraft.model_validate(DRAFT))


# ── model + build ────────────────────────────────────────────────────────────────────
def test_build_grounds_and_adds_standard_rules(journey):
    assert journey.params == ["customer_name", "amount"]
    offer = next(s for s in journey.funnel if s.stage == "Offer")
    assert [b.if_ for b in offer.side] == ["Price too high"]       # invented branch dropped
    assert [g.rule for g in journey.guardrails] == ["Never promise guaranteed returns"]
    std = {r.if_: r for r in journey.anytime if r.standard}
    assert len(std) == 3
    assert std[STANDARD_RULES["callback"]["if"]].in_script is True
    assert std[STANDARD_RULES["escalation"]["if"]].in_script is False  # quote not in script
    assert std[STANDARD_RULES["non_human"]["if"]].in_script is False


def test_journey_rejects_bad_targets_and_duplicates(journey):
    data = journey.model_dump(by_alias=True)
    data["funnel"][0]["side"][0]["goes_to"] = "Nowhere"
    with pytest.raises(ValidationError, match="goes_to"):
        Journey.model_validate(data)
    data = journey.model_dump(by_alias=True)
    data["funnel"].append(data["funnel"][0])
    with pytest.raises(ValidationError, match="duplicate stage"):
        Journey.model_validate(data)


def test_round_trip_uses_if_alias(journey):
    dumped = journey.model_dump(by_alias=True)
    assert "if" in dumped["funnel"][0]["side"][0]
    assert Journey.model_validate(dumped) == journey


# ── Jev ──────────────────────────────────────────────────────────────────────────────
def test_jev_questions_cover_the_journey(journey):
    qs = {q.key: q for q in jev_questions(journey, languages=["Hindi", "English"])}
    assert {"stage:Opening", "stage:Offer", "stage:Payment"} <= set(qs) and "order_followed" not in qs
    assert "branch:Offer:Price too high:happened" in qs and "branch:Offer:Price too high:handled" in qs
    assert "guardrail:Never promise guaranteed returns" in qs
    assert not any(k.startswith("branch:anytime:" + STANDARD_RULES["callback"]["if"]) for k in qs)
    assert qs["ended_by"].options[-1] == COMPLETED
    assert qs["answered_by"].kind == "choice" and qs["sentiment"].kind == "score"


def _answers(journey, **over):
    a = {q.key: 0.1 for q in jev_questions(journey, languages=["Hindi", "English"])
         if q.kind == "yes_no"}
    a.update({
        "answered_by": {"a live person": 0.9, "voicemail": 0.1},
        "language.primary": {"Hindi": 0.8, "English": 0.2},
        "language.secondary:English": 0.7,
        "stage:Opening": 0.95, "stage:Offer": 0.9, "stage:Payment": 0.2,
        "branch:Offer:Price too high:happened": 0.85, "branch:Offer:Price too high:handled": 0.3,
        "guardrail:Never promise guaranteed returns": 0.8,
        "standard:callback_requested": 0.9, "standard:callback_handled": 0.8,
        "objective": {"not achieved": 0.7, "fully achieved": 0.1},
        "ended_by": {"Price too high": 0.6, COMPLETED: 0.4},
        "sentiment": -1.1,
    })
    a.update(over)
    return a


def test_to_judgment_maps_numbers(journey):
    jv = to_judgment(journey, _answers(journey), languages=["Hindi", "English"])
    assert jv.answered_by == AnsweredBy.HUMAN and jv.answered_by_p == 0.9
    assert (jv.primary_language, jv.secondary_languages) == ("Hindi", ["English"])
    assert [s.reached for s in jv.stages] == [True, True, False]
    price = next(b for b in jv.branches if b.if_ == "Price too high")
    assert (price.happened, price.handled) == (True, False)
    busy = next(b for b in jv.branches if b.if_ == "Customer is busy")
    assert (busy.happened, busy.handled, busy.p_handled) == (False, None, None)
    assert jv.standard.non_human_continued is None  # a person answered
    assert (jv.standard.callback_requested, jv.standard.callback_handled) == (True, True)
    assert jv.standard.escalation_handled is None
    assert jv.objective_achieved == Objective.NOT_ACHIEVED
    assert jv.sentiment == Sentiment.NEGATIVE


# ── merge ────────────────────────────────────────────────────────────────────────────
def test_furthest_stage_scans_back_and_fills_the_funnel(journey):
    # Opening said no, Payment said no, Offer said yes -> furthest = Offer, and Opening counts as reached.
    jv = to_judgment(journey, _answers(journey, **{"stage:Opening": 0.2, "stage:Offer": 0.8}),
                     languages=["Hindi", "English"])
    assert jv.furthest_stage == "Offer"
    assert [s.reached for s in jv.stages] == [True, True, False]
    none = to_judgment(journey, _answers(journey, **{"stage:Opening": 0.1, "stage:Offer": 0.1}),
                       languages=["Hindi", "English"])
    assert none.furthest_stage is None and not any(s.reached for s in none.stages)


def test_merge_combines_without_overlap(journey):
    jv = to_judgment(journey, _answers(journey), languages=["Hindi", "English"])
    llm = LLMJudgment(summary="Customer found it expensive and asked for a callback.",
                      callback_time="tomorrow 11am",
                      wrong_values=[{"param": "amount", "expected": "3200", "said": "3400", "turn": 2}])
    out = merge(journey, "v1", jv, llm)
    assert out.furthest_stage == "Offer" and out.summary.startswith("Customer")
    assert [g.rule for g in out.guardrails_broken] == ["Never promise guaranteed returns"]
    price = next(b for b in out.branches if b.if_ == "Price too high")
    assert price.happened and price.handled is False and price.script_gap is False
    assert out.standard.callback_time == "tomorrow 11am"
    assert out.standard.callback_in_script and not out.standard.escalation_in_script
    assert out.language.primary == "Hindi" and out.wrong_values[0].said == "3400"
    dumped = out.model_dump()
    assert "disagreements" not in dumped and "order_followed" not in dumped


# ── extraction (LLM is a port; faked here) ───────────────────────────────────────────
def test_extract_journey_uses_the_port_and_grounds():
    from voiceobs.journey.extract import extract_journey

    seen = {}

    def fake(msgs, schema):
        seen["schema"], seen["user"] = schema, msgs[1]["content"]
        return schema.model_validate(DRAFT)

    journey, draft = extract_journey(SCRIPT, fake, prompt="PROMPT")
    assert seen["schema"] is JourneyDraft and SCRIPT in seen["user"]
    assert len(draft.guardrails) == 2 and len(journey.guardrails) == 1  # ungrounded one dropped
    assert journey.params == ["customer_name", "amount"]


def test_prompt_is_registered():
    from voiceobs.config import LLM_ROLES
    from voiceobs.llm import LLMRole
    from voiceobs.llm.prompts import default_prompt

    assert "GROUNDING" in default_prompt(LLMRole.SCRIPT_JOURNEY)
    assert LLM_ROLES[LLMRole.SCRIPT_JOURNEY].max_tokens >= 8000


# ── causes (RCA): derived in code, never asked ───────────────────────────────────────
def test_no_cause_questions(journey):
    assert not [q.key for q in jev_questions(journey, languages=["Hindi"]) if q.key.endswith("cause")]


def test_causes_derived_in_merge(journey):
    a = _answers(journey, **{"standard:escalation_requested": 0.9, "standard:escalation_handled": 0.1})
    jv = to_judgment(journey, a, languages=["Hindi", "English"])
    out = merge(journey, "v1", jv, LLMJudgment(unscripted=[
        {"turn": 5, "what": "Asked about taxes", "agent_response_ok": False}]))
    price = next(b for b in out.branches if b.if_ == "Price too high")
    busy = next(b for b in out.branches if b.if_ == "Customer is busy")
    assert price.cause == "not_followed" and busy.cause is None      # a script item that failed / didn't
    assert out.guardrails_broken[0].cause == "not_followed"
    assert out.standard.escalation_cause == "script_gap"             # the script never covers it
    assert out.standard.callback_cause is None                        # callback was handled
    assert out.unscripted[0].cause == "script_gap"
    kinds = {(f.kind, f.item, f.cause) for f in out.failures}
    assert ("branch", "Price too high", "not_followed") in kinds
    assert ("unscripted", "Asked about taxes", "script_gap") in kinds
    dumped = out.model_dump()
    assert "root_cause" not in dumped and "model_fault" not in dumped


def test_machine_answered_calls_drop_conversation_findings(journey):
    jv = to_judgment(journey, _answers(journey, answered_by={"voicemail": 0.9}), languages=["Hindi", "English"])
    assert jv.guardrails[0].broken  # the decision model still said yes...
    out = merge(journey, "v1", jv, LLMJudgment(unscripted=[
        {"turn": 1, "what": "x", "agent_response_ok": False}]))
    assert out.branches == [] and out.guardrails_broken == [] and out.unscripted == []  # ...but it's moot
    assert out.answered_by == AnsweredBy.VOICEMAIL and out.standard.callback_requested is False


def test_opening_and_closing_sit_outside_the_funnel():
    draft = {**DRAFT,
             "opening": {"agent": "Greet and introduce", "done_when": "Agent greeted the customer"},
             "closing": {"agent": "Thank and end", "done_when": "Agent thanked the customer and said goodbye"}}
    j = build_journey(SCRIPT, JourneyDraft.model_validate(draft))
    assert j.opening.agent == "Greet and introduce" and "Closing" not in [s.stage for s in j.funnel]
    keys = {q.key for q in jev_questions(j, languages=["Hindi"])}
    assert {"opening:done", "closing:done"} <= keys
    jv = to_judgment(j, _answers(j, **{"opening:done": 0.9, "closing:done": 0.2}), languages=["Hindi", "English"])
    assert (jv.opening_done, jv.closing_done) == (True, False)
    out = merge(j, "v1", jv, LLMJudgment())
    assert (out.opening_done, out.closing_done) == (True, False)
    # a journey without them -> None, no questions
    plain = build_journey(SCRIPT, JourneyDraft.model_validate(DRAFT))
    assert not {"opening:done", "closing:done"} & {q.key for q in jev_questions(plain, languages=["Hindi"])}
    assert to_judgment(plain, _answers(plain), languages=["Hindi", "English"]).opening_done is None
