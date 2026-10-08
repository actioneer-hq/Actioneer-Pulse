"""Clustering pass over failure moments (embedding, algo and naming mocked)."""

from __future__ import annotations

from sqlalchemy import select

from voiceobs.clustering import service
from voiceobs.config import ResolvedEmbedding
from voiceobs.db.models import Agent, AgentScript, Call, Judgment, Moment, MomentCluster


def _seed(db):
    from voiceobs.api.agents import set_agent_script

    db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
    db.flush()
    set_agent_script(db, db.get(Agent, "ag1"), "Greet. If price is too high, explain monthly cost.", None)
    prompt_id = db.scalar(select(AgentScript.prompt_id))

    def call(n):
        c = Call(external_call_id=f"c{n}", agent_id="ag1", source="upload", environment="prod",
                 status="computed", prompt_id=prompt_id)
        db.add(c)
        db.flush()
        db.add(Judgment(call_id=c.id, status="ok", journey={"format": "full"}))
        return c

    def moment(c, what, handled, turn=2):
        db.add(Moment(call_id=c.id, agent_id="ag1", prompt_id=prompt_id, kind="unscripted", item=what,
                      cause="script_gap", turn=turn, text="raw line", handled=handled))

    for i in range(4):  # 4 different calls ask about SEBI, agent struggled
        moment(call(i), "Customer asks if Liquide is SEBI registered", False)
    for i in range(4, 7):  # 3 calls already subscribed, agent handled it
        moment(call(i), "Customer says they already have the plan", True)
    chatty = call(7)  # one caller, five math questions: one call, not a pattern
    for t in range(5):
        moment(chatty, "Customer asks the agent to solve a math problem", False, turn=t)
    db.commit()


def test_unscripted_split_by_handled_and_counted_by_distinct_calls(db_sessionmaker, monkeypatch):
    with db_sessionmaker() as db:
        _seed(db)
    sent = []
    monkeypatch.setattr(service, "resolve_embedding", lambda: ResolvedEmbedding("openai", "m", "k", None, 4))

    def embed(r, texts):
        sent.extend(texts)
        return [[1.0, 0.0, 0.0] if "SEBI" in t else [0.0, 1.0, 0.0] if "plan" in t else [0.0, 0.0, 1.0]
                for t in texts]

    monkeypatch.setattr(service.gateway, "embed", embed)
    monkeypatch.setattr(service.algo, "available", lambda: True)
    seen_mcs = []

    def fake_cluster(vecs, min_cluster_size):  # group identical toy vectors
        seen_mcs.append(min_cluster_size)
        keys = {}
        return [keys.setdefault(tuple(v), len(keys)) for v in vecs]

    monkeypatch.setattr(service.algo, "cluster", fake_cluster)
    monkeypatch.setattr(service, "name_cluster", lambda kind, item, texts: texts[0][:30])

    with db_sessionmaker() as db:
        out = service.recluster(db)
    assert out["embedded"] == 12
    assert sent[0].startswith("Instruct: ") and "\nQuery:Customer" in sent[0]  # Qwen-style prefix + `what`
    with db_sessionmaker() as db:
        rows = {(c.item, c.name): c.size for c in db.scalars(select(MomentCluster))}
        assert rows == {("not_handled", "Customer asks if Liquide is SE"): 4,
                        ("handled", "Customer says they already hav"): 3}
        math = db.scalars(select(Moment).where(Moment.item.like("%math%"))).all()
        assert {m.cluster_key for m in math} == {-1}  # 5 moments but 1 call: not a pattern
    assert set(seen_mcs) == {2}  # 5% of 8 analyzed calls -> the minimum, 2

    with db_sessionmaker() as db:  # nothing changed: no re-embedding
        assert service.recluster(db)["embedded"] == 0
    monkeypatch.setenv("VOICEOBS_EMBEDDING_INSTRUCT", "Classify the intent")
    with db_sessionmaker() as db:  # new instruct -> everything re-embedded
        assert service.recluster(db)["embedded"] == 12


def test_recluster_skips_without_embedding_model(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(service, "resolve_embedding", lambda: None)
    with db_sessionmaker() as db:
        assert service.recluster(db) == {"skipped": "no embedding model configured"}


def test_leaves_get_placed_and_the_tree_is_served(db_sessionmaker, monkeypatch, authed_client):
    from tests.journey.test_models import DRAFT, SCRIPT
    from voiceobs.db.models import AgentJourney
    from voiceobs.journey import decide
    from voiceobs.journey.build import build_journey
    from voiceobs.journey.model import JourneyDraft
    from voiceobs.journey.place import NONE

    with db_sessionmaker() as db:
        _seed(db)
        row = db.scalar(select(AgentJourney))
        row.status = "ready"
        row.journey = build_journey(SCRIPT, JourneyDraft.model_validate(DRAFT)).model_dump(mode="json", by_alias=True)
        db.commit()
    monkeypatch.setattr(service, "resolve_embedding", lambda: ResolvedEmbedding("openai", "m", "k", None, 4))
    monkeypatch.setattr(service.gateway, "embed", lambda r, texts: [
        [1.0, 0.0, 0.0] if "SEBI" in t else [0.0, 1.0, 0.0] if "plan" in t else [0.0, 0.0, 1.0] for t in texts])
    monkeypatch.setattr(service.algo, "available", lambda: True)
    monkeypatch.setattr(service.algo, "cluster", lambda vecs, min_cluster_size: [
        {(1.0, 0.0, 0.0): 0, (0.0, 1.0, 0.0): 1}.get(tuple(v), 2) for v in vecs])
    monkeypatch.setattr(service, "name_cluster", lambda kind, item, texts: texts[0][:20])
    asked = []

    class Fake:
        name = "fake"

        def decide(self, text, qs):
            asked.append(text)
            q = qs[0]
            if q.key == "part":  # pass 1: SEBI -> a fact; the plan -> the Offer stage
                sebi = "SEBI" in text.split("LEAF MOMENT", 1)[1][:200]
                pick = next(o for o in q.options if ("fact" in o if sebi else "'Offer'" in o))
                return {"part": {pick: 0.9}}
            return {"match": {NONE: 0.8}}  # pass 2

    monkeypatch.setattr(decide, "resolve_decision", lambda: Fake())
    with db_sessionmaker() as db:
        service.recluster(db)
    assert sum("SCRIPT JOURNEY:" in t for t in asked) == 2   # pass 1: both leaves, whole journey
    pass2 = [t for t in asked if t.startswith("PART:")]
    assert len(pass2) == 1 and "SCRIPT JOURNEY" not in pass2[0]   # pass 2: only the Offer stage, not facts
    with db_sessionmaker() as db:
        leaves = {c.description: c.placement for c in db.scalars(select(MomentCluster)) if c.is_leaf}
    assert leaves["Customer asks if Liquide is SEBI registered"]["category"] == "fact"
    plan = leaves["Customer says they already have the plan"]
    assert (plan["category"], plan["stage"], plan["match"], plan["match_p"]) == ("branch", "Offer", None, 0.8)
    n = len(asked)
    with db_sessionmaker() as db:  # unchanged members + journey version: no new decisions
        service.recluster(db)
    assert len(asked) == n
    body = authed_client.get("/v1/agents/ag1/script-gaps").json()
    assert {x["description"] for x in body["pools"]["not_handled"] + body["pools"]["handled"] if x["leaf"]} == set(leaves)
