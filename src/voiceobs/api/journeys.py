"""Journey API: a project's journey (its script, structured) and the funnel built from judged calls.

GET  /v1/agents/{id}/journey             active script version's journey + extraction status
PUT  /v1/agents/{id}/journey             hand-edit it (validated as a Journey)
POST /v1/agents/{id}/journey/regenerate  re-run extraction for the active version
GET  /v1/agents/{id}/journey/funnel      aggregate of the journey judgments of that version's calls
GET  /v1/agents/{id}/script-gaps         the unscripted-moment cluster tree + where each leaf belongs
"""

from __future__ import annotations

from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from voiceobs.api.agents import _org_agent
from voiceobs.api.deps import now, session_dep
from voiceobs.auth import current_membership, require_role
from voiceobs.db.models import AgentJourney, AgentScript, Call, Judgment, Membership, MomentCluster
from voiceobs.journey.model import Journey
from voiceobs.worker.journey import ensure_pending

router = APIRouter(prefix="/v1/agents")


def _active(db: Session, agent_id: str) -> AgentScript | None:
    return db.scalar(select(AgentScript).where(AgentScript.agent_id == agent_id,
                                               AgentScript.active.is_(True)))


def _row(db: Session, prompt_id: str) -> AgentJourney | None:
    return db.scalar(select(AgentJourney).where(AgentJourney.prompt_id == prompt_id))


def _dict(script: AgentScript | None, row: AgentJourney | None) -> dict:
    if script is None:
        return {"status": "no_script", "version": None, "journey": None}
    return {
        "status": row.status if row else "missing", "version": script.version,
        "prompt_id": script.prompt_id, "journey": row.journey if row else None,
        "error": row.error if row else None, "edited": bool(row and row.edited),
        "model": row.model if row else None,
        "updated_at": (row.updated_at or row.created_at) if row else None,
    }


@router.get("/{agent_id}/journey")
def get_journey(agent_id: str, db: Session = Depends(session_dep),
                mem: Membership = Depends(current_membership)) -> dict:
    agent = _org_agent(db, mem, agent_id)
    script = _active(db, agent.id)
    return _dict(script, _row(db, script.prompt_id) if script else None)


@router.put("/{agent_id}/journey")
def put_journey(agent_id: str, body: dict, db: Session = Depends(session_dep),
                mem: Membership = Depends(require_role("owner", "admin"))) -> dict:
    agent = _org_agent(db, mem, agent_id)
    script = _active(db, agent.id)
    if script is None:
        raise HTTPException(422, "this project has no script")
    try:
        journey = Journey.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, {"message": "not a valid journey",
                                  "errors": [f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                                             for x in e.errors()[:20]]}) from e
    row = ensure_pending(db, script.prompt_id)
    row.journey = journey.model_dump(mode="json", by_alias=True)
    row.status, row.error, row.edited, row.updated_at = "ready", None, True, now()
    return _dict(script, row)


@router.post("/{agent_id}/journey/regenerate")
def regenerate(agent_id: str, db: Session = Depends(session_dep),
               mem: Membership = Depends(require_role("owner", "admin"))) -> dict:
    agent = _org_agent(db, mem, agent_id)
    script = _active(db, agent.id)
    if script is None:
        raise HTTPException(422, "this project has no script")
    return _dict(script, ensure_pending(db, script.prompt_id, force=True))


@router.get("/{agent_id}/journey/funnel")
def funnel(agent_id: str, db: Session = Depends(session_dep),
           mem: Membership = Depends(current_membership)) -> dict:
    """How the active script version's calls went: stage reach, branches, causes, guardrails, gaps."""
    agent = _org_agent(db, mem, agent_id)
    script = _active(db, agent.id)
    row = _row(db, script.prompt_id) if script else None
    if script is None or row is None or not row.journey:
        return {"status": _dict(script, row)["status"], "calls": 0}
    stages = [s["stage"] for s in row.journey.get("funnel", [])]
    results = [j for (j,) in db.execute(
        select(Judgment.journey).join(Call, Call.id == Judgment.call_id)
        .where(Call.agent_id == agent.id, Call.prompt_id == script.prompt_id,
               Judgment.journey.isnot(None)))]
    return {"status": row.status, "version": script.version, **aggregate(stages, results)}


def aggregate(stages: list[str], results: list[dict]) -> dict:
    """Pure aggregation of stored journey judgments (full + short) — unit-tested on its own."""
    reach = Counter()
    answered, objective, cause_totals = Counter(), Counter(), Counter()
    branches: dict[tuple, Counter] = defaultdict(Counter)
    guardrails: dict[str, Counter] = defaultdict(Counter)
    gaps_unscripted: list[str] = []
    standard = Counter()
    failures: Counter = Counter()
    human = short = 0
    for r in results:
        answered[r.get("answered_by")] += 1
        if r.get("answered_by") != "human":
            continue
        human += 1
        objective[r.get("objective_achieved")] += 1
        if r.get("format") == "short":
            short += 1
            fs = r.get("furthest_stage")
            upto = stages.index(fs) + 1 if fs in stages else 0
            for s in stages[:upto]:
                reach[s] += 1
            continue
        for s in r.get("stages", []):
            if s.get("reached"):
                reach[s["stage"]] += 1
        for k in ("opening_done", "closing_done"):
            if r.get(k):
                standard[k] += 1
        for b in r.get("branches", []):
            if not b.get("happened"):
                continue
            c = branches[(b.get("stage"), b.get("if") or b.get("if_"))]
            c["happened"] += 1
            c["handled" if b.get("handled") else "not_handled"] += 1
            if b.get("cause"):
                c[f"cause:{b['cause']}"] += 1
            if not b.get("in_script", True):
                c["not_in_script"] += 1
        for g in r.get("guardrails_broken", []):
            c = guardrails[g["rule"]]
            c["broken"] += 1
            if g.get("cause"):
                c[f"cause:{g['cause']}"] += 1
        st = r.get("standard") or {}
        for k in ("callback", "escalation"):
            if st.get(f"{k}_requested"):
                standard[f"{k}_requested"] += 1
                if st.get(f"{k}_handled"):
                    standard[f"{k}_handled"] += 1
                if not st.get(f"{k}_in_script", True):
                    standard[f"{k}_not_in_script"] += 1
        gaps_unscripted += [u.get("what", "") for u in r.get("unscripted", [])]
        for f in r.get("failures", []):  # every failure, item x cause (the grouping clusters build on)
            failures[(f["kind"], f["item"], f["cause"])] += 1
            cause_totals[f["cause"]] += 1
    return {
        "calls": len(results), "human": human, "short": short,
        "answered_by": dict(answered), "objective": dict(objective),
        "stages": [{"stage": s, "reached": reach[s]} for s in stages],
        "branches": sorted(({"stage": k[0], "if": k[1], **v} for k, v in branches.items()),
                           key=lambda x: -x.get("not_handled", 0)),
        "guardrails": sorted(({"rule": k, **v} for k, v in guardrails.items()), key=lambda x: -x["broken"]),
        "causes": dict(cause_totals), "standard": dict(standard),
        "unscripted": Counter(gaps_unscripted).most_common(20),
        "failures": [{"kind": k, "item": i, "cause": c, "calls": n}
                     for (k, i, c), n in failures.most_common(50)],
    }


@router.get("/{agent_id}/script-gaps")
def script_gaps(agent_id: str, db: Session = Depends(session_dep),
                mem: Membership = Depends(current_membership)) -> dict:
    """The active script version's unscripted-moment cluster tree (HDBSCAN inside HDBSCAN): every node with
    its parent and depth; leaves carry the description and the decision model's placement in the journey."""
    agent = _org_agent(db, mem, agent_id)
    script = _active(db, agent.id)
    if script is None:
        return {"status": "no_script", "pools": {}}
    nodes = db.scalars(select(MomentCluster).where(
        MomentCluster.agent_id == agent.id, MomentCluster.prompt_id == script.prompt_id,
        MomentCluster.kind == "unscripted").order_by(MomentCluster.item, MomentCluster.depth,
                                                     MomentCluster.size.desc())).all()
    pools: dict[str, list] = {"not_handled": [], "handled": []}
    for n in nodes:
        pools.setdefault(n.item, []).append({
            "key": n.cluster_key, "parent": n.parent_key, "depth": n.depth, "leaf": n.is_leaf,
            "name": n.name, "description": n.description, "calls": n.size, "placement": n.placement})
    return {"status": "ok", "version": script.version, "pools": pools}


@router.get("/{agent_id}/script-library")
def script_library(agent_id: str, db: Session = Depends(session_dep),
                   mem: Membership = Depends(current_membership)) -> dict:
    """Every saved script version (text + its script journey JSON) and every improved script (each
    variant's rendered text, script journey JSON and changes) for the Prompts tab."""
    from voiceobs.db.models import Prompt, ScriptProposal

    agent = _org_agent(db, mem, agent_id)
    versions = []
    for s in db.scalars(select(AgentScript).where(AgentScript.agent_id == agent.id)
                        .order_by(AgentScript.version.desc())):
        text = db.scalar(select(Prompt.text).where(Prompt.id == s.prompt_id)) or ""
        row = _row(db, s.prompt_id)
        versions.append({"version": s.version, "active": s.active, "prompt_id": s.prompt_id,
                         "created_at": s.created_at, "chars": len(text), "text": text,
                         "journey_status": row.status if row else "missing",
                         "journey": row.journey if row else None})
    by_prompt = {v["prompt_id"]: v["version"] for v in versions}
    improved = []
    for r in db.scalars(select(ScriptProposal).where(ScriptProposal.agent_id == agent.id)
                        .order_by(ScriptProposal.created_at.desc()).limit(10)):
        variants = (r.result or {}).get("variants") or {}
        improved.append({"id": r.id, "created_at": r.created_at, "status": r.status, "error": r.error,
                         "base_version": by_prompt.get(r.prompt_id), "approved_variant": r.approved_variant,
                         "variants": {k: {"chars": v.get("chars"), "text": v.get("text"),
                                          "journey": v.get("journey"), "changes": v.get("changes") or []}
                                      for k, v in variants.items()}})
    return {"versions": versions, "improved": improved}
