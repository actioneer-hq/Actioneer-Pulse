"""Analysis pipeline: decoupled stage progress, events, and judged -> clustering -> script improvement."""

from __future__ import annotations

from sqlalchemy import select

from tests.journey.test_models import DRAFT, SCRIPT
from voiceobs.db.models import Agent, AgentJourney, BackfillJob, Call, Judgment, ScriptProposal
from voiceobs.journey.build import build_journey
from voiceobs.journey.model import JourneyDraft
from voiceobs.worker import pipeline


def _seed(db, curate=False):
    from voiceobs.api.agents import set_agent_script

    db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot", curate_training_data=curate))
    db.flush()
    set_agent_script(db, db.get(Agent, "ag1"), SCRIPT, None)
    row = db.scalar(select(AgentJourney))
    row.status = "ready"
    row.journey = build_journey(SCRIPT, JourneyDraft.model_validate(DRAFT)).model_dump(mode="json", by_alias=True)
    for i in range(3):
        db.add(Call(id=f"c{i}", external_call_id=f"x{i}", agent_id="ag1", source="upload", environment="prod",
                    status="computed"))
    job = BackfillJob(org_id="default", agent_id="ag1", source="upload", status="done", options={})
    pipeline.start(job, ["x0", "x1", "x2"])
    db.add(job)
    db.commit()
    return job


def test_stages_progress_then_chain_to_clustering_and_improvement(db_sessionmaker, monkeypatch, authed_client):
    clustered = []
    monkeypatch.setattr("voiceobs.clustering.service.recluster", lambda db: clustered.append(1) or {"clusters": 4})
    with db_sessionmaker() as db:
        job = _seed(db)
        db.add(Judgment(call_id="c0", status="ok", enrich_status="ok"))
        db.add(Judgment(call_id="c1", status="ok", enrich_status="running"))
        db.commit()
        s = pipeline.progress(db, job)
        assert (s["decision"]["done"], s["decision"]["total"], s["decision"]["state"]) == (2, 3, "running")
        assert (s["llm"]["done"], s["llm"]["total"]) == (1, 2) and s["training"]["state"] == "off"
        pipeline.advance(db)
        assert not clustered and job.options["pipeline"]["events"] == []

        db.add(Judgment(call_id="c2", status="ok", enrich_status="skipped"))   # short call: no LLM part
        db.scalar(select(Judgment).where(Judgment.call_id == "c1")).enrich_status = "ok"
        db.commit()
        pipeline.advance(db)   # decision + llm done -> clustering now -> script improvement queued
        pipe = job.options["pipeline"]
        assert [e["stage"] for e in pipe["events"]] == ["decision", "llm", "clustering"] and clustered == [1]
        assert pipe["clustering"] == {"state": "done", "note": "4 clusters"} and not pipe["complete"]
        proposal = db.get(ScriptProposal, pipe["improve"]["proposal"])
        assert proposal.status == "pending"

        proposal.status = "ready"
        db.commit()
        pipeline.advance(db)
        assert job.options["pipeline"]["complete"] and job.options["pipeline"]["events"][-1]["stage"] == "improve"

    item = authed_client.get("/v1/notifications").json()["items"][0]
    assert item["agent"] == "Bot" and item["complete"] and item["stages"]["improve"]["state"] == "done"
    assert [e["stage"] for e in item["events"]] == ["decision", "llm", "clustering", "improve"]


def test_training_bar_only_when_curation_is_on(db_sessionmaker):
    with db_sessionmaker() as db:
        job = _seed(db, curate=True)
        db.add(Judgment(call_id="c0", status="ok", enrich_status="ok", curate_status="pending"))
        db.commit()
        t = pipeline.progress(db, job)["training"]
        assert (t["done"], t["total"], t["state"]) == (0, 1, "running")


def test_pipeline_state_is_saved_and_stuck_stages_rerun(db_sessionmaker, monkeypatch):
    runs = []
    monkeypatch.setattr("voiceobs.clustering.service.recluster", lambda db: runs.append(1) or {"clusters": 2})
    with db_sessionmaker() as db:
        job = _seed(db)
        for i in range(3):
            db.add(Judgment(call_id=f"c{i}", status="ok", enrich_status="skipped"))
        db.commit()
        job_id = job.id
        pipeline.advance(db)
    with db_sessionmaker() as db:  # a fresh session sees what was written, not the in-memory object
        pipe = db.get(BackfillJob, job_id).options["pipeline"]
        assert pipe["clustering"]["state"] == "done" and "clustering" in [e["stage"] for e in pipe["events"]]
        job = db.get(BackfillJob, job_id)  # simulate a worker that died mid-clustering long ago
        pipeline._save(job, {**pipe, "clustering": {"state": "running", "since": "2000-01-01T00:00:00+00:00"},
                             "improve": {}, "complete": False})
        db.commit()
        pipeline.advance(db)
    assert runs == [1, 1]


def test_progress_counts_only_this_projects_calls_and_hides_deleted_projects(db_sessionmaker, authed_client):
    with db_sessionmaker() as db:
        _seed(db)                                   # project ag1 owns calls x0..x2
        db.add(Judgment(call_id="c0", status="ok", enrich_status="ok"))
        db.add(Agent(id="ag2", org_id="default", name="Other", slug="other"))
        other = BackfillJob(org_id="default", agent_id="ag2", source="upload", status="done", options={})
        pipeline.start(other, ["x0"])               # lists a call id that now belongs to ag1
        gone = BackfillJob(org_id="default", agent_id="deleted", source="upload", status="done", options={})
        pipeline.start(gone, ["x0"])
        db.add_all([other, gone])
        db.commit()
        assert pipeline.progress(db, other)["decision"]["done"] == 0
    names = [i["agent"] for i in authed_client.get("/v1/notifications").json()["items"]]
    assert "Bot" in names and "Other" in names and None not in names and len(names) == 2
