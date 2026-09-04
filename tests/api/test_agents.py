"""Agents API: CRUD + admin gating, ingest-token mint/list/rotate/revoke, and granular
per-agent access grants."""

from __future__ import annotations


def test_agent_crud(client, login_as):
    login_as("default")  # owner
    a = client.post("/v1/agents", json={"name": "Sales Bot"}).json()
    assert a["slug"] == "sales-bot"
    assert a["id"] in {x["id"] for x in client.get("/v1/agents").json()["items"]}
    assert client.patch(f"/v1/agents/{a['id']}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.delete(f"/v1/agents/{a['id']}").json()["status"] == "ok"
    assert a["id"] not in {x["id"] for x in client.get("/v1/agents").json()["items"]}


def test_agent_create_requires_admin(client, login_as):
    login_as("default", role="viewer")
    assert client.post("/v1/agents", json={"name": "X"}).status_code == 403


def test_ingest_token_mint_list_rotate_revoke(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    minted = client.post(f"/v1/agents/{aid}/ingest-tokens", json={"name": "prod"}).json()
    assert minted["token"].startswith("vo_")
    lst = client.get(f"/v1/agents/{aid}/ingest-tokens").json()["items"]
    assert lst[0]["prefix"] == minted["prefix"]
    assert "token" not in lst[0] and "token_hash" not in lst[0]  # never echo the secret/hash
    rot = client.post(f"/v1/agents/{aid}/ingest-tokens/{minted['id']}/rotate").json()
    assert rot["token"] != minted["token"]
    revoked = {t["id"]: t["revoked"] for t in
               client.get(f"/v1/agents/{aid}/ingest-tokens").json()["items"]}
    assert revoked[minted["id"]] is True  # old one revoked by the rotate
    assert client.delete(f"/v1/agents/{aid}/ingest-tokens/{rot['id']}").json()["status"] == "ok"


def test_granular_agent_access_restricts_a_member(client, login_as, db_sessionmaker):
    from voiceobs.auth import COOKIE_NAME, hash_password, issue_session
    from voiceobs.db.models import AppUser, Membership

    login_as("default")  # owner
    a = client.post("/v1/agents", json={"name": "A"}).json()["id"]
    b = client.post("/v1/agents", json={"name": "B"}).json()["id"]
    with db_sessionmaker() as db:
        db.add(AppUser(id="u-x", email="x@co", password_hash=hash_password("pw"), is_active=True))
        db.flush()
        db.add(Membership(id="m-x", org_id="default", user_id="u-x", role="member"))
        db.commit()

    # a member with no grants sees all org agents (coarse default)
    client.cookies.set(COOKIE_NAME, issue_session("u-x"))
    assert {x["id"] for x in client.get("/v1/agents").json()["items"]} == {a, b}

    # owner grants that member access to A only → member now restricted to A
    login_as("default")
    assert client.put("/v1/orgs/default/members/m-x/agent-access",
                      json={"agent_ids": [a]}).status_code == 200
    client.cookies.set(COOKIE_NAME, issue_session("u-x"))
    assert {x["id"] for x in client.get("/v1/agents").json()["items"]} == {a}
    assert client.get(f"/v1/agents/{b}/ingest-tokens").status_code in (403, 404)
