"""Clusters tab: what fails in a project's calls, ranked by impact, and why.

GET /v1/clusters?agent_id=&range=  — for the project's ACTIVE script version, over its journey-judged
calls in range:
- `failures`: every failure group (kind, item, cause) with how often it happens, how calls with it reach
  the objective vs calls without it, `impact = share × max(0, achieved_without − achieved_with)`, and
  the lines behind it.
- `unscripted`: themes the script never covers, split by whether the agent's improvised reply worked
  (`not_handled` / `handled`); sizes are distinct calls.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voiceobs.api.agents import _org_agent
from voiceobs.api.deps import session_dep
from voiceobs.auth import current_membership
from voiceobs.clustering.service import UNSCRIPTED, group_of
from voiceobs.config import resolve_embedding
from voiceobs.db.models import AgentScript, Call, Judgment, Membership, Moment, MomentCluster

router = APIRouter(prefix="/v1/clusters")

_RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7),
           "30d": timedelta(days=30), "90d": timedelta(days=90)}
_SAMPLES = 3
_GROUP_SAMPLES = 5


@router.get("")
def clusters(agent_id: str = Query(...), range: str | None = None,
             db: Session = Depends(session_dep), mem: Membership = Depends(current_membership)) -> dict:
    agent = _org_agent(db, mem, agent_id)
    script = db.scalar(select(AgentScript).where(AgentScript.agent_id == agent.id,
                                                 AgentScript.active.is_(True)))
    if script is None:
        return {"status": "no_script", "calls": 0, "failures": [], "unscripted": []}
    stmt = (select(Call.id, Call.external_call_id, Judgment.journey).join(Judgment, Judgment.call_id == Call.id)
            .where(Call.agent_id == agent.id, Call.prompt_id == script.prompt_id, Judgment.journey.isnot(None)))
    if range in _RANGES:
        stmt = stmt.where(func.coalesce(Call.started_at, Call.created_at) >= datetime.now(UTC) - _RANGES[range])
    rows = db.execute(stmt).all()
    ids = {r[0]: r[1] for r in rows}
    moments = [m for m in db.scalars(select(Moment).where(Moment.agent_id == agent.id,
                                                          Moment.prompt_id == script.prompt_id))
               if m.call_id in ids]
    names = list(db.scalars(select(MomentCluster).where(MomentCluster.agent_id == agent.id,
                                                        MomentCluster.prompt_id == script.prompt_id)))
    out = aggregate([r[2] for r in rows], moments, names, ids)
    out["version"] = script.version
    out["status"] = ("no_embeddings" if resolve_embedding() is None
                     else "clustered" if names else "not_clustered")
    return out


def aggregate(results: list[dict], moments: list, clusters: list, call_ids: dict[str, str]) -> dict:
    """Pure: stored journey judgments + moments + named clusters -> the tab's data (unit-tested)."""
    full = [r for r in results if r.get("format") == "full" and r.get("answered_by") == "human"]
    achieved = [r.get("objective_achieved") == "achieved" for r in full]
    groups: dict[tuple, set[int]] = defaultdict(set)
    for i, r in enumerate(full):
        for f in r.get("failures") or []:
            if f.get("kind") != UNSCRIPTED:
                groups[(f["kind"], f["item"], f["cause"])].add(i)
    samples: dict[tuple, list] = defaultdict(list)  # the lines behind each failure
    for m in moments:
        g = group_of(m)
        if m.kind != UNSCRIPTED and len(samples[g]) < _GROUP_SAMPLES:
            samples[g].append(_sample(m, call_ids))
    n = len(full)
    rows = []
    for key, with_ in groups.items():
        without = n - len(with_)
        rate_with = sum(achieved[i] for i in with_) / len(with_)
        rate_without = (sum(achieved) - sum(achieved[i] for i in with_)) / without if without else None
        share = len(with_) / n
        impact = share * max(0.0, rate_without - rate_with) if rate_without is not None else 0.0
        kind, item, cause = key
        rows.append({"kind": kind, "item": item, "cause": cause, "calls": len(with_), "share": share,
                     "achieved_with": rate_with, "achieved_without": rate_without, "impact": impact,
                     "samples": samples.get(key, [])})
    rows.sort(key=lambda x: (-x["impact"], -x["calls"]))
    unscripted = [m for m in moments if m.kind == UNSCRIPTED]
    return {"calls": len(results), "human": n, "failures": rows,
            "unscripted": {pool: _themes([m for m in unscripted if bool(m.handled) == (pool == "handled")],
                                         clusters, pool, call_ids)
                           for pool in ("not_handled", "handled")},
            "unscripted_total": len({m.call_id for m in unscripted})}


def _sample(m, call_ids: dict[str, str]) -> dict:
    """What happened (the normalized description for unscripted moments) + the line, linked to its call."""
    return {"call_id": call_ids.get(m.call_id), "turn": m.turn, "text": m.text,
            "what": m.item if m.kind == UNSCRIPTED else None}


def _themes(moments: list, clusters: list, pool: str, call_ids: dict[str, str]) -> dict:
    """The leaf clusters of one unscripted pool (size = distinct calls), plus what fits no leaf."""
    leaves = {c.cluster_key: c for c in clusters
              if c.kind == UNSCRIPTED and c.item == pool and getattr(c, "is_leaf", True)}
    by: dict[int, list] = defaultdict(list)
    other = set()
    for m in moments:
        if m.cluster_key is not None and m.cluster_key in leaves:
            by[m.cluster_key].append(m)
        else:
            other.add(m.call_id)
    themes = [{"key": k, "name": leaves[k].name, "description": getattr(leaves[k], "description", None),
               "depth": getattr(leaves[k], "depth", 0), "placement": getattr(leaves[k], "placement", None),
               "calls": len({m.call_id for m in ms}),
               "samples": [_sample(m, call_ids) for m in ms[:_SAMPLES]]} for k, ms in by.items()]
    return {"themes": sorted(themes, key=lambda t: -t["calls"]), "other_calls": len(other),
            "calls": len({m.call_id for m in moments})}
