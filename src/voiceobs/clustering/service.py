"""Cluster journey failure moments per project script version, and name the clusters.

A moment is one located failure with the line that caused it (judge/journey_path.store_moments).
- Unscripted moments (what the script doesn't cover — the input for script improvement) are embedded by
  their normalized English description and split in two pools: the agent's improvised reply worked
  (`handled`) or not (`not_handled`); each pool is clustered on its own.
- Other failures cluster inside their group (kind, item, cause) by the line behind them (kept internal).
HDBSCAN with min_cluster_size = 2% of the version's full conversations; a cluster is kept only when it also
spans that many DISTINCT calls (one chatty caller can't make a pattern); the rest is "other" (-1).
Named by a short LLM name, re-named only when its members change. Best-effort: skips cleanly when no
embedding model is configured or the analytics extra is missing.
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from voiceobs.clustering import algo
from voiceobs.config import get_config, resolve_embedding, resolve_llm
from voiceobs.db.models import AgentScript, Call, Judgment, Moment, MomentCluster
from voiceobs.llm import LLMRole, gateway

log = logging.getLogger(__name__)

UNSCRIPTED = "unscripted"
_SAMPLES_TO_NAME = 8


def group_of(m: Moment) -> tuple[str, str, str]:
    """The pool a moment clusters in: unscripted moments by whether the agent's reply worked."""
    if m.kind == UNSCRIPTED:
        return (UNSCRIPTED, "handled" if m.handled else "not_handled", "script_gap")
    return (m.kind, m.item, m.cause)


def embed_text(m: Moment) -> str:
    """Unscripted: the LLM's normalized English description; otherwise the line behind the failure."""
    return m.item if m.kind == UNSCRIPTED else m.text


def model_tag() -> str:
    c = get_config()
    return f"{c.embedding_model}|{c.embedding_instruct}"[:255]


def with_instruct(text: str) -> str:
    instruct = get_config().embedding_instruct
    return f"Instruct: {instruct}\nQuery:{text}" if instruct else text


def recluster(db: Session) -> dict:
    """Full pass over the CURRENT schema (one org). The worker sets search_path per org before calling."""
    resolved = resolve_embedding()
    if resolved is None:
        return {"skipped": "no embedding model configured"}
    if not algo.available():
        return {"skipped": "analytics extra not installed"}
    embedded = _embed_pending(db, resolved)
    clusters = 0
    for agent_id, prompt_id in db.execute(
            select(AgentScript.agent_id, AgentScript.prompt_id).where(AgentScript.active.is_(True))):
        clusters += _cluster_version(db, agent_id, prompt_id)
    db.commit()
    return {"embedded": embedded, "clusters": clusters}


def _embed_pending(db: Session, resolved) -> int:
    tag = model_tag()
    pending = list(db.scalars(select(Moment).where(or_(
        Moment.embedding.is_(None), Moment.embed_model.is_(None), Moment.embed_model != tag))))
    size, done = get_config().embed_batch_size, 0
    for i in range(0, len(pending), size):
        batch = pending[i: i + size]
        try:
            vectors = gateway.embed(resolved, [with_instruct(embed_text(m)) for m in batch])
        except Exception:  # one bad batch shouldn't stop the pass
            log.exception("embedding batch failed")
            continue
        for m, v in zip(batch, vectors, strict=True):
            m.embedding, m.embed_model = v, tag
        done += len(batch)
    db.flush()
    return done


def _min_size(db: Session, agent_id: str, prompt_id: str) -> int:
    """2% (config) of the script version's full conversations, at least 2. Only full conversations with a
    person can produce moments, so short calls and machines don't inflate the bar."""
    journeys = db.scalars(select(Judgment.journey).join(Call, Call.id == Judgment.call_id)
                          .where(Call.agent_id == agent_id, Call.prompt_id == prompt_id,
                                 Judgment.journey.isnot(None)))
    full = sum(1 for j in journeys if j.get("format") == "full" and j.get("answered_by") == "human")
    return max(2, math.ceil(get_config().cluster_min_share * full))


def _cluster_version(db: Session, agent_id: str, prompt_id: str) -> int:
    tag = model_tag()
    groups: dict[tuple, list[Moment]] = defaultdict(list)
    for m in db.scalars(select(Moment).where(Moment.agent_id == agent_id, Moment.prompt_id == prompt_id,
                                             Moment.embedding.isnot(None), Moment.embed_model == tag)):
        groups[group_of(m)].append(m)
    old = {(c.kind, c.item, c.cause, c.members_hash): c for c in db.scalars(
        select(MomentCluster).where(MomentCluster.agent_id == agent_id, MomentCluster.prompt_id == prompt_id))}
    db.execute(delete(MomentCluster).where(MomentCluster.agent_id == agent_id,
                                           MomentCluster.prompt_id == prompt_id))
    need, rows = _min_size(db, agent_id, prompt_id), []
    for (kind, item, cause), ms in groups.items():
        for m in ms:
            m.cluster_key = -1  # "other" unless a node claims it below
        tree = build_tree(ms, need, max_depth=_MAX_DEPTH if kind == UNSCRIPTED else 1)
        for node in tree:
            h = hashlib.sha1("|".join(sorted(m.id for m in node.members)).encode()).hexdigest()
            prev = old.get((kind, item, cause, h))
            medoid = node.medoid() if node.leaf else None
            rows.append(MomentCluster(
                agent_id=agent_id, prompt_id=prompt_id, kind=kind, item=item, cause=cause, cluster_key=node.key,
                parent_key=node.parent, depth=node.depth, is_leaf=node.leaf, size=node.calls, members_hash=h,
                name=(prev.name if prev else None) or name_cluster(kind, item, [embed_text(m) for m in node.members]),
                medoid_moment_id=medoid.id if medoid else None,
                description=embed_text(medoid) if medoid else None,
                placement=prev.placement if prev else None, updated_at=datetime.now(UTC)))
    if rows:
        _place(db, prompt_id, [r for r in rows if r.kind == UNSCRIPTED and r.is_leaf], groups)
    db.add_all(rows)
    db.flush()
    return len(rows)


_MAX_DEPTH = 5


class Node:
    """One cluster in the tree: its moments (subtree), parent key, depth, and whether it is a leaf."""

    def __init__(self, key: int, parent: int | None, depth: int, members: list[Moment]):
        self.key, self.parent, self.depth, self.members, self.leaf = key, parent, depth, members, True

    @property
    def calls(self) -> int:
        return len({m.call_id for m in self.members})

    def medoid(self) -> Moment:
        """The member closest to the cluster's centroid."""
        x = np.asarray([list(m.embedding) for m in self.members], dtype="float32")
        x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)
        c = x.mean(0)
        return self.members[int(np.argmax(x @ (c / max(float(np.linalg.norm(c)), 1e-9))))]

    def nearest(self, n: int) -> list[Moment]:
        """The n members closest to the centroid after the medoid (for examples)."""
        x = np.asarray([list(m.embedding) for m in self.members], dtype="float32")
        x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)
        c = x.mean(0)
        order = np.argsort(-(x @ (c / max(float(np.linalg.norm(c)), 1e-9))))
        return [self.members[int(i)] for i in order[1: n + 1]]


def build_tree(moments: list[Moment], min_calls: int, max_depth: int = _MAX_DEPTH) -> list[Node]:
    """HDBSCAN, then HDBSCAN inside every cluster, up to `max_depth` levels. A child is kept only if it spans
    >= `min_calls` distinct calls; moments that fit no child stay on the parent (or are "other" at the top).
    Each moment's `cluster_key` = the deepest node holding it."""
    nodes: list[Node] = []

    def grow(members: list[Moment], parent: Node | None, depth: int) -> None:
        if depth >= max_depth or len({m.call_id for m in members}) < min_calls:
            return
        labels = algo.cluster([list(m.embedding) for m in members], min_cluster_size=min_calls)
        by: dict[int, list[Moment]] = defaultdict(list)
        for m, k in zip(members, labels, strict=True):
            if k >= 0:
                by[int(k)].append(m)
        kids = [g for g in by.values() if len({m.call_id for m in g}) >= min_calls]
        if parent is not None and (not kids or (len(kids) == 1 and len(kids[0]) == len(members))):
            return  # no finer structure: the parent is a leaf
        if kids and parent is not None:
            parent.leaf = False
        for g in sorted(kids, key=lambda g: -len({m.call_id for m in g})):
            node = Node(len(nodes), parent.key if parent else None, depth, g)
            nodes.append(node)
            for m in g:
                m.cluster_key = node.key
            grow(g, node, depth + 1)

    grow(moments, None, 0)
    return nodes


def _place(db: Session, prompt_id: str, leaves: list[MomentCluster], groups: dict) -> None:
    """Ask the decision model where each leaf belongs in the script journey (only leaves whose members or
    journey version changed). Best-effort: no decision model, no placement."""
    from voiceobs.journey.decide import render_input, resolve_decision
    from voiceobs.journey.model import Journey
    from voiceobs.journey.place import (
        component,
        match_question,
        part_question,
        pass1_input,
        pass2_input,
        to_match,
        to_part,
    )
    from voiceobs.transcript import resolve
    from voiceobs.worker.journey import ready_journey

    decision, found = resolve_decision(), ready_journey(db, prompt_id)
    if decision is None or not found:
        return
    version, data = found
    journey = Journey.model_validate(data)
    todo = [r for r in leaves if not (r.placement and r.placement.get("decided") == version)]
    if not todo:
        return
    by_id = {m.id: m for ms in groups.values() for m in ms}

    def text(lines: list[dict]) -> str:
        return render_input(None, {"lines": lines}).split("TRANSCRIPT:\n", 1)[-1]

    def window(m: Moment) -> str:
        lines = resolve(db, db.get(Call, m.call_id)).get("lines") or []
        return text([ln for ln in lines if abs((ln.get("turn_index") or 0) - m.turn) <= 3])

    evidence = []  # per leaf: (description, the medoid's whole call, windows from 2 nearby members)
    for r in todo:
        medoid = by_id[r.medoid_moment_id]
        node = Node(r.cluster_key, r.parent_key, r.depth,
                    [m for m in groups[(r.kind, r.item, r.cause)] if m.cluster_key == r.cluster_key])
        evidence.append((r.description or "", text(resolve(db, db.get(Call, medoid.call_id)).get("lines") or []),
                         [window(m) for m in node.nearest(2)]))

    # pass 1: the whole journey -> which part handles it (a stage, anytime, guardrails, facts, …)
    q1 = [part_question(journey)]
    with ThreadPoolExecutor(8) as pool:
        first = list(pool.map(lambda ev: _safe_decide(decision, pass1_input(data, *ev), q1), evidence))
    parts = [to_part(journey, a) if a is not None else (None, None, None) for a in first]

    # pass 2: only that part's JSON -> which of its items already covers it, or none of these
    def second(i: int):
        category, stage, _ = parts[i]
        comp = component(journey, category, stage) if category else None
        if not comp or not comp[1]:
            return None
        return _safe_decide(decision, pass2_input(comp[0], *evidence[i]), [match_question(comp[1])])

    with ThreadPoolExecutor(8) as pool:
        matches = list(pool.map(second, range(len(todo))))
    for r, a1, (category, stage, part_p), a2 in zip(todo, first, parts, matches, strict=True):
        if a1 is None:
            continue
        match, match_p = to_match(a2) if a2 is not None else (None, None)
        r.placement = {"category": category, "stage": stage, "part_p": part_p, "match": match,
                       "match_p": match_p, "decided": version}


def _safe_decide(decision, text: str, qs: list):
    try:
        return decision.decide(text, qs)
    except Exception:  # a failed placement never blocks clustering
        log.exception("placement failed")
        return None


def name_cluster(kind: str, item: str, texts: list[str]) -> str:
    """A 3-6 word name for one cluster, from a few of its lines. Falls back to the first line."""
    from voiceobs.llm.prompts import default_prompt

    resolved = resolve_llm(LLMRole.CLUSTER_NAMER)
    sample = list(dict.fromkeys(texts))[:_SAMPLES_TO_NAME]
    if resolved is None or not sample:
        return (sample[0] if sample else "Unnamed")[:60]
    what = ("things customers raised that the script never covers" if kind == UNSCRIPTED
            else f"calls where this failed ({kind}): {item}")
    prompt = default_prompt(LLMRole.CLUSTER_NAMER).format(what=what, lines="\n".join(f"- {t}" for t in sample))
    try:
        out = gateway.complete(resolved, [{"role": "user", "content": prompt}]).choices[0].message.content
        return (out or "").strip().strip('"').splitlines()[0][:80] or sample[0][:60]
    except Exception:  # a missing name never blocks clustering
        log.exception("cluster naming failed")
        return sample[0][:60]
