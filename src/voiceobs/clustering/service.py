"""Orchestrate semantic clustering: embed analysis prose, then (re)cluster per tenant per lever and
label each cluster. Best-effort — skips cleanly when the embedding model isn't configured. Writes
CallEmbedding, Cluster, CallCluster. Rewrites a tenant's clusters for a lever on each run."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from voiceobs.clustering import algo
from voiceobs.config import get_config, resolve_embedding, resolve_llm
from voiceobs.db.models import Call, CallCluster, CallEmbedding, Cluster, Judgment
from voiceobs.llm import LLMRole, gateway

log = logging.getLogger(__name__)

# lever -> extract the prose text from a Judgment row (None/empty = nothing to embed).
LEVERS: dict[str, Callable[[Judgment], str | None]] = {
    "root_cause": lambda j: j.root_cause,
    "suggested_fix": lambda j: j.suggested_fix,
    "summary": lambda j: j.summary,
    "guardrail_points": lambda j: " ".join(j.guardrail_violation_points or []) or None,
    "hallucination_detail": lambda j: j.hallucination_detail,
}
_EMBED_BATCH = 64
_MIN_TO_CLUSTER = 6  # fewer calls than this in a lever → skip (nothing meaningful to cluster)


def recluster(db: Session) -> dict:
    """Full pass over the CURRENT schema (one org): back-fill embeddings, then recluster each lever
    over the rolling window. The worker sets search_path per org before calling this."""
    resolved = resolve_embedding()
    if resolved is None:
        return {"skipped": "no embedding model configured"}
    if not algo.available():
        return {"skipped": "analytics extra not installed"}

    _backfill_embeddings(db, resolved)
    since = datetime.now(UTC) - timedelta(days=get_config().cluster_window_days)
    out = {lever: _recluster_lever(db, lever, since) for lever in LEVERS}
    db.commit()
    return {"clusters": out}


def _backfill_embeddings(db, resolved) -> None:
    """Embed any judged prose that doesn't have a CallEmbedding yet, per lever."""
    for lever, extract in LEVERS.items():
        have = set(db.scalars(select(CallEmbedding.call_id).where(CallEmbedding.field == lever)))
        pending: list[tuple[str, str]] = []  # (call_id, text)
        for j in db.scalars(select(Judgment)):
            if j.call_id in have:
                continue
            text = extract(j)
            if text and text.strip():
                pending.append((j.call_id, text.strip()))
        for i in range(0, len(pending), _EMBED_BATCH):
            batch = pending[i : i + _EMBED_BATCH]
            try:
                vecs = gateway.embed(resolved, [t for _, t in batch])
            except Exception as e:  # noqa: BLE001 — embedding is best-effort; skip the batch
                log.warning("embedding batch failed (%s): %s", lever, e)
                continue
            for (call_id, _), vec in zip(batch, vecs):
                db.add(CallEmbedding(call_id=call_id, field=lever,
                                     embedding=vec, model=resolved.model))
        db.flush()


def _recluster_lever(db, lever: str, since: datetime) -> int:
    rows = db.execute(
        select(CallEmbedding.call_id, CallEmbedding.embedding)
        .join(Call, Call.id == CallEmbedding.call_id)
        .where(CallEmbedding.field == lever,
               func.coalesce(Call.started_at, Call.created_at) >= since)
    ).all()
    # always rewrite this lever
    db.execute(delete(CallCluster).where(CallCluster.lever == lever))
    db.execute(delete(Cluster).where(Cluster.lever == lever))
    if len(rows) < _MIN_TO_CLUSTER:
        return 0

    call_ids = [r[0] for r in rows]
    vectors = [r[1] for r in rows]
    labels, coords = algo.cluster(vectors, min_cluster_size=get_config().cluster_min_size)

    members: dict[int, list[str]] = {}
    for call_id, key, (x, y) in zip(call_ids, labels, coords):
        db.add(CallCluster(call_id=call_id, lever=lever,
                           cluster_key=(key if key >= 0 else None), x=x, y=y))
        if key >= 0:
            members.setdefault(key, []).append(call_id)

    texts = dict(db.execute(  # call_id -> prose, for labelling exemplars
        select(Judgment.call_id, _text_col(lever))
    ).all()) if members else {}
    for key, ids in members.items():
        label = _label_cluster(lever, [texts.get(cid) for cid in ids[:5] if texts.get(cid)])
        db.add(Cluster(lever=lever, cluster_key=key, label=label, size=len(ids)))
    db.flush()
    return len(members)


def _text_col(lever: str):
    # for labelling: the DB column holding the lever's prose (guardrail_points has no single column)
    return {
        "root_cause": Judgment.root_cause,
        "suggested_fix": Judgment.suggested_fix,
        "summary": Judgment.summary,
        "hallucination_detail": Judgment.hallucination_detail,
        "guardrail_points": Judgment.summary,  # fallback; points are a JSON list, not a column
    }[lever]


def _label_cluster(lever: str, exemplars: list[str]) -> str:
    exemplars = [e for e in exemplars if e]
    if not exemplars:
        return "Unlabelled"
    resolved = resolve_llm(LLMRole.FAILURE_ANALYSIS) or resolve_llm(LLMRole.GLOBAL_CHAT)
    if resolved is None:  # no chat model → cheap heuristic
        return exemplars[0][:60]
    joined = "\n- ".join(exemplars)
    prompt = (
        f"These are examples from one cluster of voice-agent '{lever}' notes. Give a SHORT theme "
        f"label (max 6 words), no punctuation, no quotes:\n- {joined}"
    )
    try:
        resp = gateway.complete(resolved, [{"role": "user", "content": prompt}])
        return (resp.choices[0].message.content or exemplars[0][:60]).strip().strip('"')[:80]
    except Exception:  # noqa: BLE001 — labelling is best-effort
        return exemplars[0][:60]
