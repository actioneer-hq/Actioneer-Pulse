"""Judge API — config (key never echoed), on-demand run, judgment, delete cascade."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from tests.fixtures.vas_call import sample_call
from voiceobs.db.models import Call, JudgeConfig, Judgment
from voiceobs.judge.schema import JudgeOutput
from voiceobs.worker.process import process

_FAKE = JudgeOutput(sentiment="positive", objective_achieved="achieved",
                    answered_by="human", primary_language="hi", secondary_languages=[],
                    script_adherence="followed", summary="ok")


def _config(client, login_as, tenant: str = "default") -> None:
    login_as(tenant)  # admin of the org; config now scopes to the session org
    client.post("/v1/judge/config", json={
        "base_url": "https://m/v1", "model": "gpt-x", "api_key": "sk-secret",
        "params": {"reasoning": "low"},
    })


def test_config_upsert_and_key_not_echoed(client, login_as):
    _config(client, login_as)  # default org
    cfg = client.get("/v1/judge/config").json()
    assert cfg["model"] == "gpt-x"
    assert cfg["has_key"] is True
    assert "api_key" not in cfg  # write-only


def test_config_write_requires_admin(client, login_as):
    login_as("default", role="member")
    r = client.post("/v1/judge/config", json={"base_url": "https://m", "model": "x"})
    assert r.status_code == 403


def test_on_demand_judge_and_get(client, login_as, db_sessionmaker, monkeypatch):
    _config(client, login_as, "vastu-hfc")
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    client.post("/v1/traces", json=sample_call())  # has caller content -> connected
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


def test_delete_cascades_judgment(client, login_as, db_sessionmaker, monkeypatch):
    _config(client, login_as, "vastu-hfc")
    monkeypatch.setattr(sys.modules["voiceobs.judge.run"], "call_model", lambda c, m: _FAKE)
    monkeypatch.setenv("VOICEOBS_ALLOW_DELETE", "1")
    client.post("/v1/traces", json=sample_call())
    with db_sessionmaker() as db:
        process(db, db.scalars(select(Call)).one())
        db.commit()
    client.post("/v1/calls/c1/judge")
    client.delete("/v1/calls/c1", headers={"X-Voiceobs-Confirm": "c1"})
    with db_sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(Judgment)) == 0
        assert db.scalar(select(func.count()).select_from(JudgeConfig)) == 1  # tenant cfg stays
