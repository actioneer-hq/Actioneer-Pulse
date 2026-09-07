"""Cluster read endpoints — per-lever scatter + cross-lever archetypes, RBAC-scoped."""

from __future__ import annotations

from datetime import UTC, datetime

from voiceobs.db.models import Call, CallCluster, Cluster, Judgment

_ids = iter(range(10000))


def _call(db, org, *, root_key=0, fix_key=0, model_fault="llm", objective="not_achieved"):
    c = Call(external_call_id=f"c{next(_ids)}", source="livekit",
             environment="prod", status="ingested", started_at=datetime.now(UTC))
    db.add(c)
    db.flush()
    db.add(CallCluster(call_id=c.id, lever="root_cause",
                       cluster_key=root_key, x=1.0, y=2.0))
    db.add(CallCluster(call_id=c.id, lever="suggested_fix",
                       cluster_key=fix_key, x=0.0, y=0.0))
    db.add(Judgment(call_id=c.id, status="ok",
                    model_fault=model_fault, objective_achieved=objective))
    return c


def _clusters(db, org):
    db.add(Cluster(lever="root_cause", cluster_key=0, label="Skipped verification", size=3))
    db.add(Cluster(lever="suggested_fix", cluster_key=0, label="Add verification step", size=3))


def test_points_endpoint(client, login_as, db_sessionmaker):
    login_as("default")
    with db_sessionmaker() as db:
        _clusters(db, "default")
        for _ in range(3):
            _call(db, "default")
        db.commit()
    d = client.get("/v1/clusters/root_cause").json()
    assert [c["label"] for c in d["clusters"]] == ["Skipped verification"]
    assert len(d["points"]) == 3  # only this org's calls
    assert d["points"][0]["cluster_key"] == 0


def test_unknown_lever_404(client, login_as):
    login_as("default")
    assert client.get("/v1/clusters/nope").status_code == 404


def test_requires_auth(client):
    assert client.get("/v1/clusters/root_cause").status_code == 401


def test_archetypes(client, login_as, db_sessionmaker):
    login_as("default")
    with db_sessionmaker() as db:
        _clusters(db, "default")
        for _ in range(3):  # same combo → an archetype of 3
            _call(db, "default")
        _call(db, "default", objective="achieved")  # a different combo (count 1)
        db.commit()
    d = client.get("/v1/clusters/archetypes?min_count=2").json()
    assert d["dims"] == ["root_cause", "suggested_fix", "model_fault", "objective_achieved"]
    assert len(d["archetypes"]) == 1  # only the count>=2 combo survives
    top = d["archetypes"][0]
    assert top["count"] == 3
    assert top["combo"]["root_cause"] == "Skipped verification"
    assert top["combo"]["model_fault"] == "llm"
    assert top["lift"] is not None
