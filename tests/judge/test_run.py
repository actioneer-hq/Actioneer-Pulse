"""Judge orchestration — disposition gate, LLM only when connected + configured."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from voiceobs.db import Base
from voiceobs.db.models import Call, Turn
from voiceobs.judge import judge_call
from voiceobs.judge.disposition import programmatic_disposition
from voiceobs.judge.schema import JudgeOutput


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


_ids = iter(range(1000))


def _call(db, *, spoke=True, duration=30.0) -> Call:
    c = Call(external_call_id=f"c{next(_ids)}", source="livekit",
             environment="prod", status="computed", duration_s=duration)
    db.add(c)
    db.flush()
    if spoke:
        db.add(Turn(call_id=c.id, turn_index=0, turn_id="c1:0",
                    caller_transcript="haan ji", llm_spoken="boliye"))
    db.commit()
    return c


def _config(monkeypatch) -> None:
    """Configure the post-call-analysis role by setting its API key (config.resolve_llm)."""
    monkeypatch.setenv("VOICEOBS_POST_CALL_API_KEY", "sk-test")


_FAKE = JudgeOutput(sentiment="positive", objective_achieved="achieved",
                    answered_by="human", primary_language="hi", secondary_languages=["en"],
                    script_adherence="followed", summary="Caller agreed.")


def test_disposition_connected_vs_no_answer(db):
    assert programmatic_disposition(_call(db), {"lines": [{"role": "caller", "text": "hi"}]}) == "connected"
    assert programmatic_disposition(_call(db, spoke=False, duration=0.0), {"lines": []}) == "no_answer"


def test_connected_call_is_judged(db, monkeypatch):
    _config(monkeypatch)
    call = _call(db)
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    j = judge_call(db, call)
    assert j.status == "ok"
    assert j.disposition == "connected"
    assert j.sentiment == "positive"
    assert j.primary_language == "hi"
    assert j.summary == "Caller agreed."


def test_not_connected_skips_llm(db, monkeypatch):
    _config(monkeypatch)
    call = _call(db, spoke=False, duration=0.0)
    called = {"n": 0}
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model",
                        lambda c, m: called.__setitem__("n", called["n"] + 1) or _FAKE)
    j = judge_call(db, call)
    assert j.status == "skipped"
    assert j.disposition == "no_answer"
    assert j.sentiment is None
    assert called["n"] == 0  # never paid for the model


def test_no_config_skips(db, monkeypatch):
    call = _call(db)  # connected but the role has no API key configured
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    assert judge_call(db, call).status == "skipped"


def test_guardrails_passed_and_violation_persisted(db, monkeypatch):
    from voiceobs.db.models import Agent, AgentGuardrail, Prompt

    _config(monkeypatch)
    agent = Agent(org_id="t", name="Bot", slug="bot")
    db.add(agent)
    db.flush()
    p = Prompt(template_sha256="sha", text="Always verify the caller.")
    db.add(p)
    db.flush()
    db.add(AgentGuardrail(agent_id=agent.id, prompt_id=p.id, version=1, active=True))
    db.commit()

    call = _call(db)
    call.agent_id = agent.id
    db.commit()

    seen = {}
    violation = JudgeOutput(
        sentiment="neutral", objective_achieved="partial", answered_by="human",
        primary_language="en", secondary_languages=[], script_adherence="partial",
        guardrail_violation=True, guardrail_violation_points=["Skipped caller verification"],
    )

    def capture(resolved, messages):
        seen["messages"] = messages
        return violation

    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", capture)
    j = judge_call(db, call)

    assert "GUARDRAILS:\nAlways verify the caller." in seen["messages"][1]["content"]
    assert j.guardrail_violation is True
    assert j.guardrail_violation_points == ["Skipped caller verification"]


def test_model_failure_recorded_not_raised(db, monkeypatch):
    _config(monkeypatch)
    call = _call(db)

    def boom(c, m):
        raise RuntimeError("model down")

    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", boom)
    j = judge_call(db, call)
    assert j.status == "failed"
    assert "model down" in j.error
    assert j.sentiment is None


def test_failure_analysis_runs_alongside_judge(db, monkeypatch):
    from voiceobs.judge.failure_schema import FailureAnalysis

    _config(monkeypatch)  # post-call-analysis role
    monkeypatch.setenv("VOICEOBS_FAILURE_ANALYSIS_API_KEY", "sk-fa")  # failure role
    call = _call(db)
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda r, m: _FAKE)
    fa = FailureAnalysis(is_failure=True, root_cause="Agent ignored the caller's answer.",
                         model_fault="llm", model_fault_detail="ASR fine; LLM looped.",
                         suggested_fix="Add a max-reask guardrail.")
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "analyze_failure", lambda r, m: fa)
    j = judge_call(db, call)
    assert j.status == "ok"          # base judge still populated
    assert j.is_failure is True      # failure-analysis pass populated its columns
    assert j.model_fault == "llm"
    assert j.suggested_fix == "Add a max-reask guardrail."


def test_failure_analysis_skipped_when_unconfigured(db, monkeypatch):
    _config(monkeypatch)
    monkeypatch.delenv("VOICEOBS_FAILURE_ANALYSIS_API_KEY", raising=False)
    call = _call(db)
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda r, m: _FAKE)
    j = judge_call(db, call)
    assert j.status == "ok"
    assert j.is_failure is None      # failure columns left null when the role isn't configured
