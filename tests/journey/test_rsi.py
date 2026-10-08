"""Script improvement (journey/rsi) with a fake LLM and decision model."""

from __future__ import annotations

import pytest

from voiceobs.journey.build import build_journey
from voiceobs.journey.model import Fact, JourneyDraft, Persona, SideBranch
from voiceobs.journey.rsi import restructure
from voiceobs.journey.rsi.additions import NewBranch, NewFact, NewGuardrail, add_gaps
from voiceobs.journey.rsi.budget import Entry, Shortened, fit
from voiceobs.journey.rsi.club import club
from voiceobs.journey.rsi.common import Failure, Gap
from voiceobs.journey.rsi.diff import diff
from voiceobs.journey.rsi.rca import REASONS, rca
from voiceobs.journey.rsi.render import render
from voiceobs.journey.rsi.revise import RevisedBranch, RevisedStage, revise
from voiceobs.journey.rsi.run import improve

from .test_models import DRAFT, SCRIPT

RUN = "run1"


@pytest.fixture
def j():
    out = build_journey(SCRIPT, JourneyDraft.model_validate(DRAFT))
    out.persona = Persona(name="Asha", company="Acme", tone=["Warm, 1-2 sentences"], language=["Hindi or English"])
    out.facts = [Fact(topic="Pricing", text="Plan: {{amount}}")]
    out.funnel[1].say = ["The plan is {{amount}}."]
    return out


def gap(i, category, stage=None, desc="Customer asks if the company is registered"):
    return Gap(id=f"g{i}", description=desc, category=category, stage=stage, worked=False, calls=4,
               windows=["[3] customer: are you registered?\n[3] agent: umm"])


def fake_llm(answers):
    """Return the next canned answer for each schema."""
    calls = []

    def llm(task, text, schema):
        calls.append((task, text, schema))
        return answers[schema].pop(0) if isinstance(answers[schema], list) else answers[schema]

    llm.calls = calls
    return llm


class Decision:
    def __init__(self, fn):
        self.fn, self.seen = fn, []

    def decide(self, text, qs):
        self.seen.append((text, [q.key for q in qs]))
        return self.fn(text, qs)


def test_additions_land_in_their_section_with_origin(j):
    llm = fake_llm({NewBranch: [NewBranch(**{"if": "Customer asks if we are registered"}, then="Confirm and give "
                                          "the registration", goes_to="Nowhere", say=["Ji, hum registered hain."]),
                                NewBranch(**{"if": "Customer can't hear"}, then="Ask them to repeat", goes_to="Same stage")],
                    NewGuardrail: NewGuardrail(rule="Never claim approvals the script doesn't state"),
                    NewFact: NewFact(topic="Registration", text="Registration number: ask the business", needs_input=True)})
    out = add_gaps(j, [gap(1, "branch", "Offer"), gap(2, "anytime"), gap(3, "guardrail"), gap(4, "fact"),
                       gap(5, "off_topic")], llm, RUN)
    offer = next(s for s in out.funnel if s.stage == "Offer")
    new = offer.side[-1]
    assert new.if_ == "Customer asks if we are registered" and new.goes_to == "Same stage"  # invalid target fixed
    assert new.origin.change == "added" and new.origin.source == ["g1"]
    assert out.anytime[0].if_ == "Customer can't hear" and out.anytime[-1].standard  # before the standard rules
    assert out.guardrails[-1].origin and out.facts[-1].needs_input
    assert len(llm.calls) == 4  # off-topic skipped
    assert {c["change"] for c in diff(j, out)} == {"added"}


def test_club_merges_linked_new_items_in_one_section(j):
    llm = fake_llm({NewGuardrail: [NewGuardrail(rule="a"), NewGuardrail(rule="b"), NewGuardrail(rule="c")]})
    added = add_gaps(j, [gap(i, "guardrail") for i in range(3)], llm, RUN)
    assert len(added.guardrails) == len(j.guardrails) + 3

    def same(text, qs):  # a~b linked, c separate
        return {q.key: 0.9 if q.key == "pair:0:1" else 0.1 for q in qs}

    dec = Decision(same)
    merged_llm = fake_llm({NewGuardrail: NewGuardrail(rule="Never claim what the script doesn't state")})
    out = club(added, dec, merged_llm, RUN)
    rules = [g.rule for g in out.guardrails]
    assert "Never claim what the script doesn't state" in rules and "c" in rules and "a" not in rules
    merged = next(g for g in out.guardrails if g.rule.startswith("Never claim"))
    assert merged.origin.change == "merged" and set(merged.origin.source) == {"g0", "g1"}
    assert dec.seen[0][1] == ["pair:0:1", "pair:0:2", "pair:1:2"]  # one request, every pair, guardrails only


def test_rca_maps_reasons_and_training(j):
    label = {v: k for k, v in REASONS.items()}
    fails = [Failure("branch", "Price too high", 5, ["w"]), Failure("guardrail", "Never promise guaranteed returns", 3)]
    dec = Decision(lambda text, qs: {"reason": {label["vague" if "Price" in qs[0].text else "model"]: 0.8}})
    out = rca(j, fails, dec)
    assert [(r["item"], r["reason"], r["fix"]) for r in out] == [
        ("Price too high", "vague", "script"), ("Never promise guaranteed returns", "model", "training")]


def test_script_a_revises_only_failing_items(j):
    findings = [{"kind": "branch", "item": "Price too high", "calls": 5, "reason": "not_emphasized", "fix": "script"},
                {"kind": "guardrail", "item": "Never promise guaranteed returns", "calls": 3, "reason": "model",
                 "fix": "training"}]
    llm = fake_llm({RevisedBranch: RevisedBranch(**{"if": "Price too high"}, then="Say the monthly cost first, in one "
                                                 "sentence", goes_to="Same stage",
                                                 guardrail="ALWAYS answer price objections with the monthly cost")})
    out = revise(j, findings, [Failure("branch", "Price too high", 5, ["w"])], llm, RUN)
    price = next(b for s in out.funnel for b in s.side if b.if_ == "Price too high")
    assert price.then.startswith("Say the monthly cost") and price.origin.change == "revised"
    assert out.guardrails[-1].rule.startswith("ALWAYS") and len(llm.calls) == 1   # training item untouched
    assert [c["id"] for c in diff(j, out) if c["change"] == "changed"] == ["Price too high"]


def test_script_b_applies_valid_ops_and_rejects_invalid(j):
    plan = restructure.Plan(ops=[
        restructure.Op(op="remove_stage", stage="Nope", reason="x"),
        restructure.Op(op="merge_stages", stages=["Opening", "Offer"], reason="calls stall between them",
                       new_stage=restructure.NewStage(stage="Greet & Offer", agent="Greet and state the price",
                                                      done_when="Price stated")),
        restructure.Op(op="reorder", stages=["Payment"], reason="bad"),
    ])
    out, log = restructure.apply(j, plan, RUN)
    assert [s.stage for s in out.funnel] == ["Greet & Offer", "Payment"]
    merged = out.funnel[0]
    assert {b.if_ for b in merged.side} == {"Customer is busy", "Price too high"}   # branches kept
    assert [e["applied"] for e in log] == [False, True, False] and "rejected" in log[0]


def test_render_is_the_markdown_skeleton_and_fit_shortens(j):
    text = render(j)
    for h in ("# Role & Objective", "# Personality & Tone", "# Facts", "<facts>", "# Conversation Flow",
              "## Stage 2 — Offer", "- If Price too high →", "# Guardrails", "# Escalation"):
        assert h in text
    assert '- Say: "The plan is {{amount}}."' in text and render(j) == text   # deterministic
    llm = fake_llm({Shortened: Shortened(facts=[Entry(id="Pricing", text="{{amount}}")],
                                         say=[Entry(id="stage:Offer", text="{{amount}}.")])})
    out = fit(j, llm, limit=len(text) - 5)
    assert out.facts[0].text == "{{amount}}" and out.funnel[1].say == ["{{amount}}."]


def test_improve_end_to_end(j):
    llm = fake_llm({NewBranch: NewBranch(**{"if": "Customer asks if we are registered"}, then="Confirm",
                                         goes_to="Same stage"),
                    RevisedBranch: RevisedBranch(**{"if": "Price too high"}, then="Give the monthly cost",
                                                 goes_to="Same stage"),
                    restructure.Plan: restructure.Plan(ops=[]), Shortened: Shortened()})
    label = {v: k for k, v in REASONS.items()}
    dec = Decision(lambda text, qs: {q.key: 0.1 for q in qs} if qs[0].key.startswith("pair") else
                   {"reason": {label["vague"]: 0.9}})
    out = improve(j, [gap(1, "branch", "Offer")], [Failure("branch", "Price too high", 5)],
                  [{"stage": "Opening", "reached": 9}], dec, llm, RUN)
    assert set(out["variants"]) == {"additions", "A", "B"} and out["training"] == []
    a = out["variants"]["A"]
    assert {(c["change"], c["id"]) for c in a["changes"]} == {
        ("added", "Customer asks if we are registered"), ("changed", "Price too high")}
    assert a["chars"] == len(a["text"]) and "Customer asks if we are registered" in a["text"]


def test_wrong_place_is_decided_in_code_from_failure_stages(j):
    label = {v: k for k, v in REASONS.items()}
    asked = []
    dec = Decision(lambda text, qs: asked.append(qs[0].text) or {"reason": {label["vague"]: 0.8}})
    fails = [Failure("guardrail", "Never promise guaranteed returns", 4, stages=["Offer", "Offer", "Offer", "Payment"]),
             Failure("guardrail", "Never ask for an OTP", 1, stages=["Offer"]),                 # too thin to move
             Failure("guardrail", "Always say please", 3, stages=["Opening", "Offer", "Payment"]),   # spread
             Failure("branch", "Price too high", 3, stages=["Offer", "Offer", "Offer"])]          # written there
    out = {r["item"]: r for r in rca(j, fails, dec)}
    g = out["Never promise guaranteed returns"]
    assert (g["reason"], g["stage"], g["fix"]) == ("wrong_place", "Offer", "script")
    assert out["Always say please"]["reason"] == "vague" and out["Price too high"]["reason"] == "vague"
    assert out["Never ask for an OTP"]["reason"] == "vague"
    assert len(asked) == 3 and "buried" not in " ".join(REASONS.values())


def test_script_a_moves_situations_and_writes_rules_into_the_stage(j):
    j.anytime.insert(0, j.anytime[0].model_copy(update={"if_": "Customer asks for a discount", "standard": False}))
    findings = [{"kind": "branch", "item": "Customer asks for a discount", "calls": 3, "reason": "wrong_place",
                 "stage": "Payment", "fix": "script"},
                {"kind": "guardrail", "item": "Never promise guaranteed returns", "calls": 4, "reason": "wrong_place",
                 "stage": "Offer", "fix": "script"},
                {"kind": "branch", "item": "Price too high", "calls": 2, "reason": "vague", "fix": "script"}]
    llm = fake_llm({RevisedStage: RevisedStage(agent="State the price. Never promise guaranteed returns.",
                                               done_when="Price stated"),
                    RevisedBranch: RevisedBranch(**{"if": "Price too high"}, then="Give the monthly cost",
                                                 goes_to="Same stage", guardrail="NOT ADDED")})
    out = revise(j, findings, [], llm, RUN)
    pay = next(s for s in out.funnel if s.stage == "Payment")
    assert pay.side[-1].if_ == "Customer asks for a discount" and pay.side[-1].origin.change == "moved"
    assert all(r.if_ != "Customer asks for a discount" for r in out.anytime)
    offer = next(s for s in out.funnel if s.stage == "Offer")
    assert "Never promise guaranteed returns" in offer.agent and offer.side   # rule written in, branches kept
    assert all(g.rule != "NOT ADDED" for g in out.guardrails)               # only not_emphasized adds one


def test_diff_shows_a_situation_moved_into_a_stage(j):
    out = j.model_copy(deep=True)
    rule = out.anytime.pop(0)
    out.funnel[2].side.append(SideBranch(**rule.model_dump(by_alias=True, exclude={"standard", "in_script"})))
    assert [(c["change"], c["id"], c["at"]) for c in diff(j, out)] == [("moved", rule.if_, "Payment")]
