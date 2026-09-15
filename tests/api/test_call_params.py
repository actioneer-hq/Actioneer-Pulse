"""Per-agent call parameters: gating, prompt injection, CSV upload + reconciliation."""
from __future__ import annotations

from sqlalchemy import select

from voiceobs.db.models import Agent, Call, CallParams
from voiceobs.judge.prompt import build_messages
from voiceobs.judge.run import judge_call, resolve_params


def _agent(db, params_required=False) -> str:
    from voiceobs.db.models import Organization
    if db.get(Organization, "default") is None:
        db.add(Organization(id="default", name="default", slug="default"))
    a = Agent(id="a1", org_id="default", name="A", slug="a", params_required=params_required)
    db.add(a)
    db.flush()
    return a.id


def _call(db, ext="call-1", connected=True) -> Call:
    c = Call(external_call_id=ext, source="s", environment="prod", agent_id="a1",
             status="ingested", metric_version=1)
    db.add(c)
    db.flush()
    # a connected call needs a turn so programmatic_disposition sees a conversation
    if connected:
        from voiceobs.db.models import Turn
        db.add(Turn(call_id=c.id, turn_index=0, turn_id=f"{ext}:0", trigger="endpoint",
                    caller_transcript="hi", llm_spoken="hello"))
    db.flush()
    return c


def test_gate_skips_when_required_and_absent(db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        _agent(db, params_required=True)
        c = _call(db)
        j = judge_call(db, c)
        assert j.status == "skipped"
        assert j.error == "no_params"


def test_not_gated_when_agent_flag_off(db_sessionmaker, monkeypatch) -> None:
    # params_required=False → the no_params gate never fires (may skip for other reasons like no LLM)
    with db_sessionmaker() as db:
        _agent(db, params_required=False)
        c = _call(db)
        j = judge_call(db, c)
        assert j.error != "no_params"


def test_resolve_params_by_call_key(db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        _agent(db, params_required=True)
        c = _call(db, ext="call-xyz")
        db.add(CallParams(agent_id="a1", call_key="call-xyz",
                          params={"call_id": "call-xyz", "EmiAmount": "21226"}))
        db.flush()
        assert resolve_params(db, c) == {"call_id": "call-xyz", "EmiAmount": "21226"}


def test_params_injected_into_judge_prompt() -> None:
    msgs = build_messages("SCRIPT $(EmiAmount)", {"lines": [{"role": "agent", "text": "hi"}]},
                          params={"EmiAmount": "21226", "CustomerName": "Suyog"})
    user = msgs[1]["content"]
    assert "CALL PARAMETERS" in user
    assert "EmiAmount: 21226" in user and "CustomerName: Suyog" in user


def test_no_params_block_when_absent() -> None:
    msgs = build_messages("SCRIPT", {"lines": []}, params=None)
    assert "CALL PARAMETERS" not in msgs[1]["content"]


def test_upload_csv_upserts_and_reports(authed_client, db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        _agent(db)
        _call(db, ext="c-100")  # already ingested → should count as matched
        db.commit()
    csv = "call_id,CustomerName,EmiAmount\nc-100,Suyog,21226\nc-200,Ravi,15000\n"
    r = authed_client.post("/v1/agents/a1/call-params", json={"csv": csv})
    assert r.status_code == 200
    body = r.json()
    assert body["row_count"] == 2
    assert body["matched"] == 1  # only c-100 exists
    with db_sessionmaker() as db:
        rows = db.scalars(select(CallParams).where(CallParams.agent_id == "a1")).all()
        assert {x.call_key for x in rows} == {"c-100", "c-200"}


def test_upload_bad_key_column_400(authed_client, db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        _agent(db)
        db.commit()
    r = authed_client.post("/v1/agents/a1/call-params",
                           json={"csv": "foo,bar\n1,2\n", "key_column": "call_id"})
    assert r.status_code == 400


def test_params_required_toggle(authed_client, db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        _agent(db)
        db.commit()
    r = authed_client.put("/v1/agents/a1/params-required", json={"params_required": True})
    assert r.status_code == 200 and r.json()["params_required"] is True
    with db_sessionmaker() as db:
        assert db.get(Agent, "a1").params_required is True


def test_delete_agent_cleans_params(authed_client, db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        _agent(db)
        db.add(CallParams(agent_id="a1", call_key="c-1", params={"x": "1"}))
        db.commit()
    assert authed_client.delete("/v1/agents/a1").status_code == 200
    with db_sessionmaker() as db:
        assert db.scalars(select(CallParams).where(CallParams.agent_id == "a1")).all() == []
