"""HIGH-1 regression: the chat SQL tool's curated views enforce per-agent RBAC + per-call binding
server-side (not via the prompt), so a restricted role can't read other agents' data by writing
`SELECT * FROM calls`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

import voiceobs.db.session as dbs
from voiceobs.chat.sql import run_agent_sql
from voiceobs.db.models import Call, Judgment
from voiceobs.db.provision import provision_org


def _seed(db):
    provision_org(db, "default", "Default")  # builds the ag_ views with the RBAC predicate
    for cid, agent in (("cA", "agA"), ("cB", "agB")):
        c = Call(external_call_id=cid, agent_id=agent, source="x",
                 environment="prod", status="ingested", started_at=datetime.now(UTC))
        db.add(c)
        db.flush()
        db.add(Judgment(call_id=c.id, status="ok", summary=f"summary {cid}"))
    db.commit()


def _run(sm, query, **kw):
    saved = (dbs._engine, dbs._Session, dbs._AgentSession)
    dbs._engine, dbs._Session, dbs._AgentSession = sm.kw["bind"], sm, sm
    try:
        return run_agent_sql("default", query, **kw)
    finally:
        dbs._engine, dbs._Session, dbs._AgentSession = saved


def test_restricted_agent_sees_only_its_calls(db_sessionmaker):
    with db_sessionmaker() as db:
        _seed(db)
    r = _run(db_sessionmaker, "SELECT external_call_id FROM calls ORDER BY external_call_id",
             visible_agents=["agA"])
    assert [row[0] for row in r["rows"]] == ["cA"]


def test_admin_sees_all_calls(db_sessionmaker):
    with db_sessionmaker() as db:
        _seed(db)
    r = _run(db_sessionmaker, "SELECT external_call_id FROM calls ORDER BY external_call_id",
             visible_agents=None)  # None = owner/admin
    assert [row[0] for row in r["rows"]] == ["cA", "cB"]


def test_via_call_views_respect_scope(db_sessionmaker):
    # judgments has no agent_id — the view reaches it through the call join; restricted role sees only its own
    with db_sessionmaker() as db:
        _seed(db)
    r = _run(db_sessionmaker, "SELECT summary FROM judgments ORDER BY summary", visible_agents=["agB"])
    assert [row[0] for row in r["rows"]] == ["summary cB"]


def test_per_call_binding_limits_to_one_call(db_sessionmaker):
    with db_sessionmaker() as db:
        _seed(db)
        call_a_id = db.scalar(select(Call.id).where(Call.external_call_id == "cA"))
    # admin, but bound to call cA → cannot see cB even with SELECT *
    r = _run(db_sessionmaker, "SELECT external_call_id FROM calls",
             visible_agents=None, call_id=call_a_id)
    assert [row[0] for row in r["rows"]] == ["cA"]


def test_unset_scope_fails_closed(db_sessionmaker):
    # a query run with no scope set at all returns nothing (fail-closed), never everything
    with db_sessionmaker() as db:
        _seed(db)
    r = _run(db_sessionmaker, "SELECT external_call_id FROM calls", visible_agents=[])
    assert r["rows"] == []
