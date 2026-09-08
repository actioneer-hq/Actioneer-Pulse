"""Judge API — on-demand run, judgment fetch, delete cascade. Model config comes from
config.py + env (VOICEOBS_POST_CALL_API_KEY), not the DB."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from tests.fixtures.livekit_call import sample_call
from voiceobs.db.models import Call, Judgment
from voiceobs.judge.schema import JudgeOutput
from voiceobs.worker.process import process

_FAKE = JudgeOutput(sentiment="positive", objective_achieved="achieved",
                    answered_by="human", primary_language="hi", secondary_languages=[],
                    script_adherence="followed", summary="ok")


def _configure_judge(monkeypatch) -> None:
    """Activate the post-call-analysis role (config.resolve_llm reads this key)."""
    monkeypatch.setenv("VOICEOBS_POST_CALL_API_KEY", "sk-secret")


def test_on_demand_judge_and_get(client, login_as, db_sessionmaker, monkeypatch, drain):
    _configure_judge(monkeypatch)
    login_as("vastu-hfc")
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    client.post("/v1/traces", json=sample_call())  # has caller content -> connected
    drain()
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()

    r = client.post("/v1/calls/c1/judge")
    assert r.status_code == 200
    assert r.json()["sentiment"] == "positive"
    assert client.get("/v1/calls/c1/judgment").json()["disposition"] == "connected"


def test_judgment_404_before_run(client, login_as):
    client.post("/v1/traces", json=sample_call())
    login_as("vastu-hfc")
    assert client.get("/v1/calls/c1/judgment").status_code == 404


def test_delete_cascades_judgment(client, login_as, db_sessionmaker, monkeypatch, drain):
    _configure_judge(monkeypatch)
    login_as("vastu-hfc")
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    monkeypatch.setenv("VOICEOBS_ALLOW_DELETE", "1")
    client.post("/v1/traces", json=sample_call())
    drain()
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()
    client.post("/v1/calls/c1/judge")
    client.delete("/v1/calls/c1", headers={"X-Voiceobs-Confirm": "c1"})
    with db_sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(Judgment)) == 0
