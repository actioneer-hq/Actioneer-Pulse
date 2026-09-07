"""Clustering orchestration — embed backfill + per-lever cluster/label writes (algo mocked)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from voiceobs.clustering import service
from voiceobs.config import ResolvedEmbedding
from voiceobs.db.models import Call, CallCluster, CallEmbedding, Cluster, Judgment


def test_recluster_embeds_and_writes(db_sessionmaker, monkeypatch):
    with db_sessionmaker() as db:
        for i in range(8):
            c = Call(external_call_id=f"c{i}", source="livekit",
                     environment="prod", status="ingested", started_at=datetime.now(UTC))
            db.add(c)
            db.flush()
            db.add(Judgment(call_id=c.id, status="ok",
                            root_cause=f"cause {'A' if i < 4 else 'B'}"))
        db.commit()

    # mock the expensive/external bits: embedding model, the embed call, the LLM label, the algo.
    monkeypatch.setattr(service, "resolve_embedding",
                        lambda: ResolvedEmbedding("openai", "m", "k", None, 4))
    monkeypatch.setattr(service.gateway, "embed",
                        lambda r, texts: [[float(len(t)), 0.0, 0.0, 0.0] for t in texts])
    monkeypatch.setattr(service, "resolve_llm", lambda role: None)  # label falls back to exemplar
    monkeypatch.setattr(service.algo, "available", lambda: True)
    monkeypatch.setattr(service.algo, "cluster",
                        lambda vecs, min_cluster_size=8: (
                            [0 if i < len(vecs) // 2 else 1 for i in range(len(vecs))],
                            [(float(i), 0.0) for i in range(len(vecs))]))

    with db_sessionmaker() as db:
        service.recluster(db)

    with db_sessionmaker() as db:
        n_emb = db.scalar(select(func.count()).select_from(CallEmbedding)
                          .where(CallEmbedding.field == "root_cause"))
        n_cl = db.scalar(select(func.count()).select_from(Cluster)
                         .where(Cluster.lever == "root_cause"))
        n_cc = db.scalar(select(func.count()).select_from(CallCluster)
                         .where(CallCluster.lever == "root_cause"))
        labels = db.scalars(select(Cluster.label).where(Cluster.lever == "root_cause")).all()
    assert n_emb == 8          # all 8 root_cause proses embedded
    assert n_cl == 2           # two clusters written
    assert n_cc == 8           # every call assigned
    assert all(labels)         # each cluster got a (fallback) label


def test_recluster_skips_without_embedding_model(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(service, "resolve_embedding", lambda: None)
    with db_sessionmaker() as db:
        assert service.recluster(db) == {"skipped": "no embedding model configured"}
