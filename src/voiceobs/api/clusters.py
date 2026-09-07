"""Read endpoints for the Clusters tab: per-lever 2D scatter data, and the cross-lever archetype
table (recurring combinations of cluster labels + enums). RBAC-scoped exactly like boards/read —
tenant + visible_agent_ids, joined through Call for agent scope."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from voiceobs.api.deps import session_dep
from voiceobs.auth import current_membership, visible_agent_ids
from voiceobs.clustering.service import LEVERS
from voiceobs.db.models import Call, CallCluster, Cluster, Judgment, Membership

router = APIRouter(prefix="/v1/clusters")

_RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7),
           "30d": timedelta(days=30), "90d": timedelta(days=90)}
_POINT_CAP = 3000  # recharts SVG scatter degrades past a few thousand points → downsample
# The dimensions that make up a cross-lever archetype (cluster labels + judgment enums).
_ARCHETYPE_LEVERS = ("root_cause", "suggested_fix")
_ARCHETYPE_ENUMS = ("model_fault", "objective_achieved")


def _scope(stmt: Select, db: Session, mem: Membership, agent_id: str | None,
           range_key: str | None) -> Select:
    # tenant scope = the schema (search_path); only agent-level RBAC + filters remain.
    ids = visible_agent_ids(db, mem)
    if ids is not None:
        stmt = stmt.where(Call.agent_id.in_(ids))
    if agent_id:
        stmt = stmt.where(Call.agent_id == agent_id)
    if range_key and range_key in _RANGES:
        since = datetime.now(UTC) - _RANGES[range_key]
        stmt = stmt.where(func.coalesce(Call.started_at, Call.created_at) >= since)
    return stmt


@router.get("/archetypes")
def archetypes(
    mem: Membership = Depends(current_membership),
    db: Session = Depends(session_dep),
    agent_id: str | None = None,
    range: str | None = None,
    min_count: int = Query(2, ge=1),
) -> dict:
    """Recurring cross-lever combinations: (root-cause theme × fix theme × model_fault × objective),
    with count and lift (observed vs. independence-expected)."""
    # per-call cluster label per lever
    label_of = {(lev, key): lbl for lev, key, lbl in db.execute(
        select(Cluster.lever, Cluster.cluster_key, Cluster.label)).all()}
    per_call: dict[str, dict[str, str]] = defaultdict(dict)
    cc_rows = db.execute(_scope(
        select(Call.external_call_id, CallCluster.lever, CallCluster.cluster_key)
        .join(Call, Call.id == CallCluster.call_id)
        .where(CallCluster.lever.in_(_ARCHETYPE_LEVERS), CallCluster.cluster_key.isnot(None)),
        db, mem, agent_id, range)).all()
    for cid, lever, key in cc_rows:
        lbl = label_of.get((lever, key))
        if lbl:
            per_call[cid][lever] = lbl
    # enums per call
    for cid, mf, obj in db.execute(_scope(
            select(Call.external_call_id, Judgment.model_fault, Judgment.objective_achieved)
            .join(Judgment, Judgment.call_id == Call.id), db, mem, agent_id, range)).all():
        if cid in per_call:
            per_call[cid]["model_fault"] = mf or "none"
            per_call[cid]["objective_achieved"] = obj or "unknown"

    dims = (*_ARCHETYPE_LEVERS, *_ARCHETYPE_ENUMS)
    combos, marginals = Counter(), {d: Counter() for d in dims}
    total = 0
    for vals in per_call.values():
        if not all(d in vals for d in _ARCHETYPE_LEVERS):  # need the theme dims present
            continue
        tup = tuple(vals.get(d, "—") for d in dims)
        combos[tup] += 1
        total += 1
        for d in dims:
            marginals[d][vals.get(d, "—")] += 1

    items = []
    for tup, n in combos.most_common():
        if n < min_count:
            continue
        expected = total
        for d, v in zip(dims, tup):
            expected *= marginals[d][v] / total
        # consistency: of all calls sharing this root cause, how many follow this exact path
        cause_total = marginals[_ARCHETYPE_LEVERS[0]][tup[0]]
        items.append({
            "combo": dict(zip(dims, tup)), "count": n,
            "cause_total": cause_total,
            "consistency": round(n / cause_total, 3) if cause_total else None,
            "lift": round(n / expected, 2) if expected else None,
        })
    return {"dims": list(dims), "total": total, "archetypes": items}


@router.get("/{lever}")
def points(
    lever: str,
    mem: Membership = Depends(current_membership),
    db: Session = Depends(session_dep),
    agent_id: str | None = None,
    range: str | None = None,
) -> dict:
    """The 2D scatter for one lever: clusters (id, label, size) + points (call, x, y, cluster)."""
    if lever not in LEVERS:
        raise HTTPException(404, "unknown lever")
    clusters = [
        {"key": c.cluster_key, "label": c.label, "size": c.size}
        for c in db.scalars(select(Cluster).where(Cluster.lever == lever)
            .order_by(Cluster.size.desc()))
    ]
    rows = db.execute(_scope(
        select(Call.external_call_id, CallCluster.x, CallCluster.y, CallCluster.cluster_key)
        .join(Call, Call.id == CallCluster.call_id)
        .where(CallCluster.lever == lever), db, mem, agent_id, range)).all()
    if len(rows) > _POINT_CAP:  # deterministic stride downsample
        rows = rows[:: (len(rows) // _POINT_CAP) + 1]
    points = [{"call_id": cid, "x": x, "y": y, "cluster_key": key} for cid, x, y, key in rows]
    return {"lever": lever, "clusters": clusters, "points": points}
