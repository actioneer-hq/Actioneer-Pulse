"""Script improvement API: start a run, the worker runs it (fakes), approve mints the next version."""

from __future__ import annotations

from sqlalchemy import select

from tests.journey.test_models import DRAFT, SCRIPT
from voiceobs.db.models import Agent, AgentJourney, AgentScript, ScriptProposal
from voiceobs.journey.build import build_journey
from voiceobs.journey.model import JourneyDraft
from voiceobs.journey.rsi import restructure
from voiceobs.journey.rsi.budget import Shortened


def test_start_run_approve(authed_client, db_sessionmaker):
    from voiceobs.worker.rsi import run_one

    with db_sessionmaker() as db:
        db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
        db.commit()
    assert authed_client.post("/v1/agents/ag1/script-rsi").status_code == 422   # no script yet
    authed_client.put("/v1/agents/ag1/script", json={"text": SCRIPT})
    with db_sessionmaker() as db:
        row = db.scalar(select(AgentJourney))
        row.status = "ready"
        row.journey = build_journey(SCRIPT, JourneyDraft.model_validate(DRAFT)).model_dump(mode="json", by_alias=True)
        db.commit()
    started = authed_client.post("/v1/agents/ag1/script-rsi").json()
    assert started["status"] == "pending"

    def llm(task, text, schema):
        return {restructure.Plan: restructure.Plan(ops=[]), Shortened: Shortened()}[schema]

    class Dec:
        def decide(self, text, qs):
            return {}

    with db_sessionmaker() as db:
        run_one(db, db.get(ScriptProposal, started["id"]), llm=llm, decision=Dec())
        db.commit()
    runs = authed_client.get("/v1/agents/ag1/script-rsi").json()["items"]
    assert runs[0]["status"] == "ready" and set(runs[0]["result"]["variants"]) == {"additions", "A", "B"}
    ok = authed_client.post(f"/v1/agents/ag1/script-rsi/{started['id']}/approve", json={"variant": "B"}).json()
    assert ok["version"] == 2 and ok["journey"] == "ready"
    with db_sessionmaker() as db:
        active = db.scalar(select(AgentScript).where(AgentScript.active.is_(True)))
        assert active.version == 2 and db.get(ScriptProposal, started["id"]).approved_variant == "B"
    lib = authed_client.get("/v1/agents/ag1/script-library").json()
    assert [v["version"] for v in lib["versions"]] == [2, 1] and lib["versions"][0]["active"]
    assert lib["versions"][0]["journey_status"] == "ready" and lib["versions"][0]["journey"]["funnel"]
    run = lib["improved"][0]
    assert run["base_version"] == 1 and run["approved_variant"] == "B"
    assert set(run["variants"]) == {"additions", "A", "B"} and run["variants"]["B"]["journey"]["funnel"]
