"""C1 regression: ingest write endpoints require a token and enforce agent ownership of the call.

Under dev-open (SQLite tests) an absent token is allowed (local flow), so these tests exercise the
ownership wall by presenting a *valid but wrong* agent's token — which must 404, while the owning
agent's token succeeds."""

from __future__ import annotations

from sqlalchemy import select

from tests.fixtures.livekit_call import sample_call
from voiceobs.db.models import Call


def _agent_token(client, name: str) -> str:
    aid = client.post("/v1/agents", json={"name": name}).json()["id"]
    return client.post(f"/v1/agents/{aid}/ingest-tokens", json={"name": "t"}).json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_transcript_upload_enforces_agent_ownership(client, login_as, db_sessionmaker, drain):
    login_as("default")
    tok_a = _agent_token(client, "Agent A")
    tok_b = _agent_token(client, "Agent B")

    # ingest a call as agent A → the call is owned by A
    client.post("/v1/traces", json=sample_call(), headers=_auth(tok_a))
    drain()
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        agent_a = call.agent_id
    assert agent_a is not None  # ownership was recorded from the token

    # agent B's token must not write to agent A's call → 404 (never leak existence)
    r = client.post("/v1/calls/c1/transcript", json={"text": "hijacked"}, headers=_auth(tok_b))
    assert r.status_code == 404

    # the owning agent's token succeeds
    r = client.post("/v1/calls/c1/transcript", json={"text": "legit"}, headers=_auth(tok_a))
    assert r.status_code == 200


def test_invalid_token_is_rejected(client, login_as):
    login_as("default")
    _agent_token(client, "Agent A")  # ensure an agent exists
    r = client.post("/v1/calls/c1/transcript", json={"text": "x"},
                    headers={"Authorization": "Bearer vo_bogus_token"})
    assert r.status_code == 401
