"""Agent scripts: versioning, hash dedup, admin gating, and per-call pinning."""

from __future__ import annotations

from sqlalchemy import select

from tests.fixtures.livekit_call import sample_call
from voiceobs.db.models import Call


def test_set_and_version_bump(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    v1 = client.put(f"/v1/agents/{aid}/script", json={"text": "Follow the sales flow."}).json()
    assert v1["version"] == 1 and len(v1["sha256"]) == 64
    v2 = client.put(f"/v1/agents/{aid}/script", json={"text": "New flow, be concise."}).json()
    assert v2["version"] == 2 and v2["sha256"] != v1["sha256"]
    # history has both, newest first, one active
    hist = client.get(f"/v1/agents/{aid}/scripts").json()["items"]
    assert [h["version"] for h in hist] == [2, 1]
    assert [h["active"] for h in hist] == [True, False]


def test_identical_text_no_new_version(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot", "script": "Be nice."}).json()["id"]
    same = client.put(f"/v1/agents/{aid}/script", json={"text": "Be nice."}).json()
    assert same["version"] == 1  # unchanged text → still v1
    assert len(client.get(f"/v1/agents/{aid}/scripts").json()["items"]) == 1


def test_get_script_returns_text(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot", "script": "Confirm the appt."}).json()["id"]
    got = client.get(f"/v1/agents/{aid}/script").json()
    assert got["text"] == "Confirm the appt." and got["version"] == 1


def test_set_requires_admin(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    login_as("default", role="viewer")
    assert client.put(f"/v1/agents/{aid}/script", json={"text": "x"}).status_code == 403


def test_call_pins_active_script_version(client, login_as, db_sessionmaker, drain):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot", "script": "v1 script"}).json()["id"]
    tok = client.post(f"/v1/agents/{aid}/ingest-tokens", json={}).json()["token"]

    # ingest a call for this agent → it pins v1
    client.post("/v1/traces", json=sample_call(), headers={"Authorization": f"Bearer {tok}"})
    drain()
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert call.prompt_id is not None
        first_prompt = call.prompt_id

    # change the script to v2, then confirm the already-ingested call still points at v1
    client.put(f"/v1/agents/{aid}/script", json={"text": "v2 script"})
    client.post("/v1/traces", json=sample_call(), headers={"Authorization": f"Bearer {tok}"})
    drain()
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert call.prompt_id == first_prompt  # pinned; not rewritten to v2
