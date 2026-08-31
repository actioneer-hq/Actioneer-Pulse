"""Judge orchestration — disposition gate, LLM only when connected + configured."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from voiceobs.db import Base
from voiceobs.db.models import Call, JudgeConfig, Turn
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
    c = Call(tenant_id="t", external_call_id=f"c{next(_ids)}", source="voice-cascade",
             environment="prod", status="computed", duration_s=duration)
    db.add(c)
    db.flush()
    if spoke:
        db.add(Turn(call_id=c.id, tenant_id="t", turn_index=0, turn_id="c1:0",
                    caller_transcript="haan ji", llm_spoken="boliye"))
    db.commit()
    return c


def _config(db) -> None:
    db.add(JudgeConfig(tenant_id="t", base_url="https://m/v1", model="gpt-x", enabled=True))
    db.commit()


_FAKE = JudgeOutput(sentiment="positive", objective_achieved="achieved",
                    answered_by="human", primary_language="hi", secondary_languages=["en"],
                    script_adherence="followed", summary="Caller agreed.")


def test_disposition_connected_vs_no_answer(db):
    assert programmatic_disposition(_call(db), {"lines": [{"role": "caller", "text": "hi"}]}) == "connected"
    assert programmatic_disposition(_call(db, spoke=False, duration=0.0), {"lines": []}) == "no_answer"


def test_connected_call_is_judged(db, monkeypatch):
    _config(db)
    call = _call(db)
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    j = judge_call(db, call)
    assert j.status == "ok"
    assert j.disposition == "connected"
    assert j.sentiment == "positive"
    assert j.primary_language == "hi"
    assert j.summary == "Caller agreed."


def test_not_connected_skips_llm(db, monkeypatch):
    _config(db)
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
    call = _call(db)  # connected but no JudgeConfig
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    assert judge_call(db, call).status == "skipped"


def test_model_failure_recorded_not_raised(db, monkeypatch):
    _config(db)
    call = _call(db)

    def boom(c, m):
        raise RuntimeError("model down")

    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", boom)
    j = judge_call(db, call)
    assert j.status == "failed"
    assert "model down" in j.error
    assert j.sentiment is None
