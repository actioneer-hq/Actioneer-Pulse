"""Journey judge wiring: short format, decision client, LLM messages, extraction worker, judge path,
journey API + funnel."""

from __future__ import annotations

import json
import sys

import httpx
import pytest
from sqlalchemy import select

import voiceobs.judge.journey_path  # noqa: F401 — patched by the judge-path tests
from voiceobs.db.models import Agent, AgentJourney, AgentScript, Call, Judgment, Prompt, Turn
from voiceobs.journey import decide
from voiceobs.journey.build import build_journey
from voiceobs.journey.jev import (
    OPENING_END,
    JevQuestion,
    customer_turns,
    is_short,
    jev_questions,
    short_questions,
    to_short,
)
from voiceobs.journey.llm import LLMJudgment, llm_messages
from voiceobs.journey.model import JourneyDraft
from voiceobs.judge.schema import AnsweredBy, Objective

from .test_models import DRAFT, SCRIPT


@pytest.fixture
def journey():
    return build_journey(SCRIPT, JourneyDraft.model_validate(DRAFT))


def _tr(*roles):
    return {"lines": [{"turn_index": i, "role": r, "text": "x"} for i, r in enumerate(roles)]}


# ── short format ─────────────────────────────────────────────────────────────────────
def test_short_routing():
    assert customer_turns(_tr("agent", "caller", "agent", "caller")) == 2
    assert is_short(_tr("caller", "caller", "caller")) and not is_short(_tr(*["caller"] * 4))
    assert is_short({"text": "agent: hi\ncustomer: hello"})
    assert not is_short({})  # can't tell -> full


def test_short_questions_and_mapping(journey):
    qs = short_questions(journey, languages=["Hindi", "English"])
    assert [q.key for q in qs] == ["answered_by", "language.primary", "furthest_stage",
                                   "objective", "sentiment"]
    assert qs[2].options[0] == OPENING_END
    r = to_short(journey, {
        "answered_by": {"a live person": 0.9}, "language.primary": {"Hindi": 0.8},
        "furthest_stage": {"Offer": 0.7, OPENING_END: 0.3},
        "objective": {"not achieved": 0.9}, "sentiment": -1.0})
    assert (r.format, r.answered_by, r.furthest_stage) == ("short", AnsweredBy.HUMAN, "Offer")
    assert r.objective_achieved == Objective.NOT_ACHIEVED
    assert to_short(journey, {"answered_by": {"voicemail": 1.0}, "language.primary": {"Hindi": 1},
                              "furthest_stage": {OPENING_END: 1.0}, "objective": {"not achieved": 1},
                              }).furthest_stage is None


def test_questions_are_call_scoped(journey):
    qs = {q.key: q for q in jev_questions(journey, languages=["Hindi"])}
    assert "never came up" in qs["guardrail:Never promise guaranteed returns"].text
    assert qs["branch:Offer:Price too high:happened"].text.startswith("In this call")


# ── decision client ──────────────────────────────────────────────────────────────────
def test_decision_client_chunks_and_maps(monkeypatch):
    qs = [JevQuestion(key=f"y{i}", kind="yes_no", text="t") for i in range(250)]
    qs += [JevQuestion(key="c", kind="choice", text="t", options=["a", "b"]),
           JevQuestion(key="s", kind="score", text="t", scale=(-2, 2))]
    sizes = []

    def fake_post(url, json, headers, timeout):
        sizes.append(len(json["questions"]))
        answers = []
        for q in json["questions"]:
            if q["type"] == "predicate":
                answers.append({"type": "predicate", "name": q["name"], "probability": 0.7})
            elif q["type"] == "choice":
                answers.append({"type": "choice", "name": q["name"], "choice": "o1",
                                "probabilities": [{"value": "o0", "probability": 0.2},
                                                  {"value": "o1", "probability": 0.8}]})
            else:
                answers.append({"type": "score", "name": q["name"], "score": 3.0})
        return httpx.Response(200, json={"answers": answers}, request=httpx.Request("POST", url))

    monkeypatch.setattr(decide.httpx, "post", fake_post)
    out = decide.OpenAIDecisions("k").decide("text", qs)
    assert sorted(sizes) == [52, 200]
    assert out["y249"] == 0.7 and out["c"] == {"a": 0.2, "b": 0.8} and out["s"] == pytest.approx(1.0)


def test_render_input_marks_turns():
    text = decide.render_input({"name": "A"}, {"lines": [{"turn_index": 0, "role": "agent", "text": "hi"},
                                                        {"turn_index": 0, "role": "caller", "text": "yo"}]})
    assert '"name": "A"' in text and "[0] agent: hi" in text and "[0] customer: yo" in text
    with_script = decide.render_input({}, {"lines": []}, "Floor price is 3200.")
    assert with_script.startswith("THE AGENT'S SCRIPT") and "Floor price is 3200." in with_script


def test_llm_messages_put_journey_in_a_cached_block():
    msgs = llm_messages("PROMPT {schema}", '{"objective": "x"}', "CALL")
    assert "properties" in msgs[0]["content"]
    blocks = msgs[1]["content"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"} and "objective" in blocks[0]["text"]
    assert blocks[1]["text"] == "CALL"


# ── extraction worker + judge path (DB) ──────────────────────────────────────────────
def _seed(db, *, customer_lines: int):
    from voiceobs.api.agents import set_agent_script

    agent = Agent(id="ag1", org_id="default", name="Bot", slug="bot")
    db.add(agent)
    db.flush()
    set_agent_script(db, agent, SCRIPT, None)
    prompt_id = db.scalar(select(AgentScript.prompt_id).where(AgentScript.agent_id == "ag1"))
    call = Call(external_call_id="c1", agent_id="ag1", source="upload", environment="prod",
                status="computed", duration_s=30.0, prompt_id=prompt_id)
    db.add(call)
    db.flush()
    for i in range(customer_lines):
        db.add(Turn(call_id=call.id, turn_index=i, turn_id=f"c1:{i}", caller_transcript="haan",
                    llm_spoken="offer"))
    db.commit()
    return call, prompt_id


def test_script_save_queues_and_worker_extracts(db_sessionmaker):
    from voiceobs.worker.journey import extract_one, ready_journey

    with db_sessionmaker() as db:
        _, prompt_id = _seed(db, customer_lines=1)
        row = db.scalar(select(AgentJourney).where(AgentJourney.prompt_id == prompt_id))
        assert row.status == "pending"
        extract_one(db, row, structured=lambda msgs, schema: schema.model_validate(DRAFT), prompt="P")
        db.commit()
        assert row.status == "ready" and row.journey["params"] == ["customer_name", "amount"]
        assert ready_journey(db, prompt_id)[1]["objective"] == DRAFT["objective"]


class _FakeDecision:
    name = "fake:decision"

    def __init__(self, answers):
        self.answers, self.seen, self.texts = answers, [], []

    def decide(self, text, questions):
        self.seen.append(len(questions))
        self.texts.append(text)
        return self.answers


def _ready(db, prompt_id, journey):
    row = db.scalar(select(AgentJourney).where(AgentJourney.prompt_id == prompt_id))
    row.status, row.journey = "ready", journey.model_dump(mode="json", by_alias=True)
    db.commit()


def test_judge_uses_short_path(db_sessionmaker, monkeypatch, journey):
    from voiceobs.judge import judge_call

    fake = _FakeDecision({"answered_by": {"a live person": 0.9}, "language.primary": {"Hindi": 1.0},
                          "furthest_stage": {"Offer": 1.0},
                          "objective": {"not achieved": 1.0}, "sentiment": -1.0})
    monkeypatch.setattr(sys.modules["voiceobs.judge.journey_path"], "resolve_decision", lambda: fake)
    with db_sessionmaker() as db:
        call, prompt_id = _seed(db, customer_lines=2)
        _ready(db, prompt_id, journey)
        j = judge_call(db, call)
        assert j.status == "ok" and j.journey["format"] == "short" and fake.seen == [5]
        assert fake.texts[0].startswith("THE AGENT'S SCRIPT") and SCRIPT in fake.texts[0]
        assert j.enrich_status == "skipped"
        assert (j.answered_by, j.objective_achieved, j.primary_language) == ("human", "not_achieved", "Hindi")


def test_full_path_runs_in_three_stages(db_sessionmaker, monkeypatch, journey):
    from voiceobs.db.models import TrainingSample
    from voiceobs.journey import curate as cur
    from voiceobs.judge import journey_stages as stages
    from voiceobs.judge import judge_call

    answers = {q.key: 0.1 for q in jev_questions(journey) if q.kind == "yes_no"}
    answers.update({"answered_by": {"a live person": 0.9}, "language.primary": {"Hindi": 1.0},
                    "stage:Opening": 0.9, "stage:Offer": 0.9,
                    "branch:Offer:Price too high:happened": 0.9, "branch:Offer:Price too high:handled": 0.1,
                    "guardrail:Never promise guaranteed returns": 0.9,
                    "objective": {"not achieved": 1.0}, "ended_by": {"Price too high": 1.0}, "sentiment": 0.0})
    fake = _FakeDecision(answers)
    monkeypatch.setattr(sys.modules["voiceobs.judge.journey_path"], "resolve_decision", lambda: fake)
    monkeypatch.setenv("VOICEOBS_POST_CALL_API_KEY", "k")  # journey roles fall back to it
    seen_msgs = []

    def fake_llm(resolved, msgs):
        seen_msgs.append(msgs[-1]["content"][-1]["text"])
        # failures from stage 1, in order: 0 = Price too high, 1 = the guardrail, 2 = missed stage Payment
        return LLMJudgment(summary="Short chat.", timeline=[{"turn": 0, "item": "opening"},
                                                            {"turn": 1, "item": "Offer"}],
                           failure_turns=[{"id": 0, "turn": 2}, {"id": 1, "turn": 3}, {"id": 2, "turn": None}])

    monkeypatch.setattr(stages, "judge_llm", fake_llm)
    monkeypatch.setattr(cur, "structured", lambda resolved, msgs, model: cur.Curation(corrections=[
        cur.Correction(id=0, corrected="It is just 270 a month."),
        cur.Correction(id=1, corrected="[Do not promise returns]"),          # an instruction -> dropped
        cur.Correction(id=2, corrected="offer"),                             # same as said -> dropped
    ]))
    with db_sessionmaker() as db:
        call, prompt_id = _seed(db, customer_lines=5)
        _ready(db, prompt_id, journey)
        # stage 1: decision model only — failures listed, no spans, enrichment queued
        j = judge_call(db, call)
        assert j.status == "ok" and j.journey["format"] == "full" and fake.seen[0] > 15
        assert j.enrich_status == "pending" and j.summary is None and j.guardrail_violation is True
        assert {f["item"] for f in j.journey["failures"]} >= {"Price too high", "Payment"}
        assert all(not f["turns"] for f in j.journey["failures"])
        # stage 2: the LLM places each failure (the missed stage falls back to the timeline); curation queued
        assert stages.enrich_call(db, call) is True
        assert "FAILURES" in seen_msgs[0] and "id 0:" in seen_msgs[0]
        spans = {f["item"]: (f["turns"], f["target_turn"]) for f in j.journey["failures"]}
        assert spans["Price too high"] == ([2], 2)
        assert spans["Never promise guaranteed returns"] == ([3], 3)
        assert spans["Payment"][1] == 2          # first agent turn after the furthest stage (Offer @1)
        assert j.summary == "Short chat." and j.enrich_status == "ok" and j.curate_status == "pending"
        # stage 3: one sample survives the code filters
        assert stages.curate_call(db, call) == 1
        db.commit()
        s = db.scalar(select(TrainingSample))
        assert (s.turn, s.item, s.observed, s.corrected) == (2, "Price too high", "offer",
                                                              "It is just 270 a month.")
        assert j.curate_status == "ok"


def test_judge_falls_back_without_decision_model(db_sessionmaker, monkeypatch, journey):
    from voiceobs.judge import judge_call

    monkeypatch.setattr(sys.modules["voiceobs.judge.journey_path"], "resolve_decision", lambda: None)
    with db_sessionmaker() as db:
        call, prompt_id = _seed(db, customer_lines=2)
        _ready(db, prompt_id, journey)
        j = judge_call(db, call)
        assert j.journey is None and j.status == "skipped"  # classic judge, no LLM key configured


# ── API ──────────────────────────────────────────────────────────────────────────────
def test_journey_api_and_funnel(authed_client, db_sessionmaker, journey):
    with db_sessionmaker() as db:
        db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
        db.commit()
    assert authed_client.get("/v1/agents/ag1/journey").json()["status"] == "no_script"
    authed_client.put("/v1/agents/ag1/script", json={"text": SCRIPT})
    assert authed_client.get("/v1/agents/ag1/journey").json()["status"] == "pending"

    bad = authed_client.put("/v1/agents/ag1/journey", json={"objective": "x", "funnel": []})
    assert bad.status_code == 422
    ok = authed_client.put("/v1/agents/ag1/journey", json=journey.model_dump(mode="json", by_alias=True))
    assert ok.status_code == 200 and ok.json()["status"] == "ready" and ok.json()["edited"] is True
    assert authed_client.post("/v1/agents/ag1/journey/regenerate").json()["status"] == "pending"

    # funnel over stored judgments
    authed_client.put("/v1/agents/ag1/journey", json=journey.model_dump(mode="json", by_alias=True))
    with db_sessionmaker() as db:
        prompt_id = db.scalar(select(Prompt.id))
        for n, res in enumerate([
            {"format": "short", "answered_by": "human", "furthest_stage": "Offer",
             "objective_achieved": "not_achieved"},
            {"format": "full", "answered_by": "human", "objective_achieved": "partial",
             "stages": [{"stage": "Opening", "reached": True}, {"stage": "Offer", "reached": True},
                        {"stage": "Payment", "reached": False}],
             "branches": [{"stage": "Offer", "if": "Price too high", "happened": True, "handled": False,
                           "cause": "not_followed", "in_script": True}],
             "guardrails_broken": [{"rule": "Never promise guaranteed returns", "cause": "script_gap"}],
             "standard": {"escalation_requested": True, "escalation_handled": False,
                          "escalation_in_script": False},
             "unscripted": [{"what": "Asked about taxes"}],
             "failures": [{"kind": "branch", "item": "Price too high", "cause": "not_followed", "turns": [2]},
                          {"kind": "unscripted", "item": "Asked about taxes", "cause": "script_gap",
                           "turns": [5]}]},
            {"format": "short", "answered_by": "voicemail"},
        ]):
            c = Call(external_call_id=f"x{n}", agent_id="ag1", source="upload", environment="prod",
                     status="computed", prompt_id=prompt_id)
            db.add(c)
            db.flush()
            db.add(Judgment(call_id=c.id, status="ok", journey=res))
        db.commit()
    f = authed_client.get("/v1/agents/ag1/journey/funnel").json()
    assert (f["calls"], f["human"], f["short"]) == (3, 2, 1)
    assert {s["stage"]: s["reached"] for s in f["stages"]} == {"Opening": 2, "Offer": 2, "Payment": 0}
    assert f["branches"][0]["not_handled"] == 1 and f["causes"] == {"not_followed": 1, "script_gap": 1}
    assert f["failures"][0] == {"kind": "branch", "item": "Price too high", "cause": "not_followed", "calls": 1}
    assert f["standard"]["escalation_not_in_script"] == 1
    assert f["unscripted"] == [["Asked about taxes", 1]]
    assert json.dumps(f)  # serializable
