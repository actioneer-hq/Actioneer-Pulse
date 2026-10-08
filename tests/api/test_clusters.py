"""Clusters tab: failure groups ranked by impact, variants and script-gap themes."""

from __future__ import annotations

from types import SimpleNamespace as NS

from sqlalchemy import select

from voiceobs.api.clusters import aggregate
from voiceobs.db.models import Agent, Call, Judgment, Moment, MomentCluster, Prompt


def _full(achieved: bool, *failures):
    return {"format": "full", "answered_by": "human",
            "objective_achieved": "achieved" if achieved else "not_achieved",
            "failures": [{"kind": k, "item": i, "cause": c} for k, i, c in failures]}


PRICE = ("branch", "Price too high", "not_followed")
GREAT = ("guardrail", "Never say Great", "not_followed")


def test_aggregate_ranks_by_impact():
    results = ([_full(False, PRICE)] * 4 + [_full(True, PRICE)] * 1     # price: 1/5 achieve
               + [_full(True, GREAT)] * 3                             # "Great": everyone achieves
               + [_full(True)] * 2
               + [{"format": "short", "answered_by": "human"}, {"format": "full", "answered_by": "voicemail"}])
    out = aggregate(results, [], [], {})
    assert (out["calls"], out["human"]) == (12, 10)
    top, second = out["failures"]
    assert (top["item"], top["calls"], top["share"]) == ("Price too high", 5, 0.5)
    assert top["achieved_with"] == 0.2 and top["achieved_without"] == 1.0
    assert abs(top["impact"] - 0.4) < 1e-9                                # 0.5 x (1.0 - 0.2)
    assert second["item"] == "Never say Great" and second["impact"] == 0.0


def test_aggregate_samples_and_unscripted_pools():
    m = lambda kind, item, cause, key, call, handled=None: NS(
        kind=kind, item=item, cause=cause, cluster_key=key, call_id=call, turn=3, text=f"line {call}",
        handled=handled)
    moments = [m(*PRICE, None, "c1"), m(*PRICE, None, "c2"),
               m("unscripted", "Asks about SEBI", "script_gap", 0, "c3", False),
               m("unscripted", "Asks about SEBI", "script_gap", 0, "c4", False),
               m("unscripted", "Asks the date", "script_gap", -1, "c5", True)]
    clusters = [NS(kind="unscripted", item="not_handled", cause="script_gap", cluster_key=0, name="SEBI questions")]
    out = aggregate([_full(False, PRICE)], moments, clusters, {f"c{i}": f"x{i}" for i in range(1, 6)})
    row = out["failures"][0]
    assert row["samples"][0] == {"call_id": "x1", "turn": 3, "text": "line c1", "what": None}
    assert "variants" not in row
    struggled, ok = out["unscripted"]["not_handled"], out["unscripted"]["handled"]
    assert struggled["themes"][0]["name"] == "SEBI questions" and struggled["themes"][0]["calls"] == 2
    assert struggled["themes"][0]["samples"][0]["what"] == "Asks about SEBI"
    assert ok == {"themes": [], "other_calls": 1, "calls": 1} and out["unscripted_total"] == 3


def test_endpoint_uses_active_script_version(authed_client, db_sessionmaker):
    with db_sessionmaker() as db:
        db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
        db.commit()
    assert authed_client.get("/v1/clusters", params={"agent_id": "ag1"}).json()["status"] == "no_script"
    authed_client.put("/v1/agents/ag1/script", json={"text": "Greet the customer."})
    with db_sessionmaker() as db:
        prompt_id = db.scalar(select(Prompt.id))
        c = Call(external_call_id="x1", agent_id="ag1", source="upload", environment="prod",
                 status="computed", prompt_id=prompt_id)
        db.add(c)
        db.flush()
        db.add(Judgment(call_id=c.id, status="ok", journey=_full(False, PRICE)))
        db.add(Moment(call_id=c.id, agent_id="ag1", prompt_id=prompt_id, kind="branch", item="Price too high",
                      cause="not_followed", turn=2, text="too costly", cluster_key=0))
        db.add(MomentCluster(agent_id="ag1", prompt_id=prompt_id, kind="branch", item="Price too high",
                             cause="not_followed", cluster_key=0, name="Too costly", size=1, members_hash="h"))
        db.commit()
    body = authed_client.get("/v1/clusters", params={"agent_id": "ag1", "range": "30d"}).json()
    assert body["version"] == 1 and body["failures"][0]["item"] == "Price too high"
    assert body["failures"][0]["samples"][0]["call_id"] == "x1"
    assert body["status"] in ("no_embeddings", "clustered")


def test_requires_auth(client):
    assert client.get("/v1/clusters", params={"agent_id": "ag1"}).status_code == 401
