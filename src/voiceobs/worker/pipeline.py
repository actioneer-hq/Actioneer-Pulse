"""The analysis pipeline of one upload / backfill job — decoupled stages, tracked on the job.

After ingestion the job's calls flow through stages that run in different workers:
- decision: the decision model judged the call (judge worker)
- llm: the LLM's part (summary, unscripted moments) — calls that need it
- training: training data curated (journey-llm worker) — only when the project turns it on
then, chained here as soon as decision + llm are complete:
- clustering: script-gap clusters for the project (run immediately, not on the 10-minute cadence)
- improve: a script-improvement run (journey/rsi), queued as soon as clustering is done
Each stage's completion is recorded as an event (the notification bell rings on new events). State lives
in `job.options["pipeline"]`; progress is counted from the judgments, so it is always current.
"""

from __future__ import annotations

import copy
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from voiceobs.db.models import Agent, AgentScript, BackfillJob, Call, Judgment, ScriptProposal

log = logging.getLogger(__name__)
_STUCK = timedelta(hours=2)   # judging not done this long after ingestion -> stop waiting
_RETRY = timedelta(minutes=10)  # a stage left "running" this long (worker died) -> run it again
_RECENT = timedelta(days=3)
LABELS = {"decision": "Decision model", "llm": "LLM analysis", "training": "Training data",
          "clustering": "Clustering", "improve": "Script improvement"}


def _now() -> datetime:
    return datetime.now(UTC)


def start(job: BackfillJob, judged: list[str]) -> None:
    _save(job, {"calls": judged, "events": [], "complete": False})


def _pipe(job: BackfillJob) -> dict:
    """A deep copy: mutating the stored JSON in place hides the change from SQLAlchemy (never saved)."""
    return copy.deepcopy((job.options or {}).get("pipeline") or {})


def _save(job: BackfillJob, pipe: dict) -> None:
    job.options = {**(job.options or {}), "pipeline": copy.deepcopy(pipe)}
    flag_modified(job, "options")


def progress(db: Session, job: BackfillJob) -> dict:
    """The stages of one job: {key: {label, done, total, state}} with state waiting / running / done /
    skipped / off."""
    pipe = _pipe(job)
    ids = pipe.get("calls") or []
    rows = db.execute(select(Judgment.status, Judgment.enrich_status, Judgment.curate_status)
                      .join(Call, Call.id == Judgment.call_id)
                      .where(Call.external_call_id.in_(ids), Call.agent_id == job.agent_id)).all() if ids else []
    decided = [r for r in rows if r[0] in ("ok", "failed", "skipped")]
    llm_need = [r for r in decided if r[1] not in (None, "skipped")]
    llm_done = [r for r in llm_need if r[1] in ("ok", "failed")]
    train_need = [r for r in decided if r[2] in ("pending", "running", "ok", "failed")]
    train_done = [r for r in train_need if r[2] in ("ok", "failed")]
    agent = db.get(Agent, job.agent_id) if job.agent_id else None
    decision_ok = len(decided) >= len(ids)

    def bar(key: str, done: int, total: int, finished: bool, **extra) -> dict:
        state = "done" if finished else ("running" if total or done else "waiting")
        return {"label": LABELS[key], "done": done, "total": total, "state": state, **extra}

    stages = {
        "decision": bar("decision", len(decided), len(ids), decision_ok),
        "llm": bar("llm", len(llm_done), len(llm_need), decision_ok and len(llm_done) == len(llm_need)),
    }
    if agent is not None and agent.curate_training_data:
        stages["training"] = bar("training", len(train_done), len(train_need),
                                 decision_ok and len(train_done) == len(train_need))
    else:
        stages["training"] = {"label": LABELS["training"], "done": 0, "total": 0, "state": "off"}
    for key in ("clustering", "improve"):
        s = pipe.get(key) or {}
        stages[key] = {"label": LABELS[key], "done": 0, "total": 0, "state": s.get("state", "waiting"),
                       **({"note": s["note"]} if s.get("note") else {})}
    return stages


def _event(pipe: dict, key: str, note: str | None = None) -> None:
    if all(e["stage"] != key for e in pipe["events"]):
        pipe["events"].append({"stage": key, "label": LABELS[key], "at": _now().isoformat(),
                               **({"note": note} if note else {})})


def advance(db: Session) -> int:
    """Move every open pipeline in the current schema forward. Returns how many changed."""
    since = _now() - _RECENT
    changed = 0
    for job in db.scalars(select(BackfillJob).where(BackfillJob.created_at >= since)):
        pipe = _pipe(job)
        if not pipe or pipe.get("complete"):
            continue
        pipe.setdefault("events", [])
        before = len(pipe["events"])
        stages = progress(db, job)
        for key in ("decision", "llm", "training"):
            if stages[key]["state"] == "done":
                _event(pipe, key)
        done_at = job.finished_at.replace(tzinfo=job.finished_at.tzinfo or UTC) if job.finished_at else None
        stuck = bool(done_at and _now() - done_at > _STUCK)
        judged = stages["decision"]["state"] == "done" and stages["llm"]["state"] == "done"
        cl = pipe.get("clustering") or {}
        stale = cl.get("state") == "running" and _now() - datetime.fromisoformat(
            cl.get("since", "2000-01-01T00:00:00+00:00")) > _RETRY
        if (judged or stuck) and (not cl or stale):
            pipe["clustering"] = {"state": "running", "since": _now().isoformat()}
            _save(job, pipe)
            db.commit()
            pipe["clustering"] = _cluster(db)
            _event(pipe, "clustering", pipe["clustering"].get("note"))
            pipe["improve"] = _queue_improvement(db, job)
        imp = pipe.get("improve") or {}
        if imp.get("state") == "running" and imp.get("proposal"):
            row = db.get(ScriptProposal, imp["proposal"])
            if row is not None and row.status in ("ready", "failed"):
                imp = {**imp, "state": "done" if row.status == "ready" else "failed",
                       **({"note": (row.error or "")[:200]} if row.status == "failed" else {})}
                pipe["improve"] = imp
        if imp.get("state") in ("done", "failed", "skipped"):
            _event(pipe, "improve", imp.get("note"))
            pipe["complete"] = True
        if len(pipe["events"]) != before or pipe.get("complete") or pipe != _pipe(job):
            _save(job, pipe)
            db.commit()
            changed += 1
    return changed


def _cluster(db: Session) -> dict:
    from voiceobs.clustering.service import recluster

    try:
        out = recluster(db)
    except Exception as e:
        log.exception("pipeline clustering failed")
        return {"state": "failed", "note": str(e)[:200]}
    if "skipped" in out:
        return {"state": "skipped", "note": out["skipped"]}
    return {"state": "done", "note": f"{out.get('clusters', 0)} clusters"}


def _queue_improvement(db: Session, job: BackfillJob) -> dict:
    from voiceobs.worker.journey import ready_journey

    script = db.scalar(select(AgentScript).where(AgentScript.agent_id == job.agent_id,
                                                 AgentScript.active.is_(True))) if job.agent_id else None
    if script is None or not ready_journey(db, script.prompt_id):
        return {"state": "skipped", "note": "no script with a ready script journey"}
    row = ScriptProposal(agent_id=job.agent_id, prompt_id=script.prompt_id, status="pending")
    db.add(row)
    db.flush()
    return {"state": "running", "proposal": row.id}
