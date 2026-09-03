"""Auth + orgs endpoints: signup-when-empty, login/logout/me, invite-only after first,
accept-invite, org create/list, member management + admin gating."""

from __future__ import annotations


def test_signup_open_only_for_first_user(client):
    r = client.post("/v1/auth/signup", json={"email": "a@co.com", "password": "pw",
                                             "org_name": "Acme"})
    assert r.status_code == 200
    body = r.json()
    assert body["org"]["name"] == "Acme"
    # cookie set → authenticated
    assert client.get("/v1/auth/me").json()["user"]["email"] == "a@co.com"
    # second signup is closed
    assert client.post("/v1/auth/signup", json={"email": "b@co.com", "password": "pw"}).status_code == 403


def test_login_logout_me(client):
    client.post("/v1/auth/signup", json={"email": "a@co.com", "password": "pw"})
    client.post("/v1/auth/logout")
    assert client.get("/v1/auth/me").status_code == 401  # cookie cleared
    assert client.post("/v1/auth/login", json={"email": "a@co.com", "password": "wrong"}).status_code == 401
    assert client.post("/v1/auth/login", json={"email": "a@co.com", "password": "pw"}).status_code == 200
    me = client.get("/v1/auth/me").json()
    assert me["memberships"][0]["role"] == "owner"


def test_me_requires_auth(client):
    assert client.get("/v1/auth/me").status_code == 401


def test_org_create_and_list(client):
    client.post("/v1/auth/signup", json={"email": "a@co.com", "password": "pw", "org_name": "First"})
    r = client.post("/v1/orgs", json={"name": "Second"})
    assert r.status_code == 200
    orgs = client.get("/v1/orgs").json()["items"]
    assert {o["name"] for o in orgs} == {"First", "Second"}
    assert all(o["role"] == "owner" for o in orgs)


def test_member_invite_and_accept(client):
    r = client.post("/v1/auth/signup", json={"email": "owner@co.com", "password": "pw"})
    org_id = r.json()["org"]["id"]
    # owner invites a new member → gets an invite token
    inv = client.post(f"/v1/orgs/{org_id}/members", json={"email": "new@co.com", "role": "member"})
    assert inv.status_code == 200
    token = inv.json()["invite_token"]
    assert token
    members = client.get(f"/v1/orgs/{org_id}/members").json()["items"]
    assert {m["email"] for m in members} == {"owner@co.com", "new@co.com"}
    # invited user accepts, sets a password, is logged in
    client.post("/v1/auth/logout")
    acc = client.post("/v1/auth/accept-invite", json={"token": token, "password": "newpw"})
    assert acc.status_code == 200
    assert client.get("/v1/auth/me").json()["user"]["email"] == "new@co.com"


def test_member_management_requires_admin(client, db_sessionmaker):
    from voiceobs.auth import COOKIE_NAME, hash_password, issue_session
    from voiceobs.db.models import AppUser, Membership

    client.post("/v1/auth/signup", json={"email": "owner@co.com", "password": "pw"})
    org_id = client.get("/v1/orgs").json()["items"][0]["id"]
    # a plain member added directly
    with db_sessionmaker() as db:
        db.add(AppUser(id="u-mem", email="mem@co.com", password_hash=hash_password("pw"),
                       is_active=True))
        db.flush()
        db.add(Membership(id="m-mem", org_id=org_id, user_id="u-mem", role="member"))
        db.commit()
    client.cookies.set(COOKIE_NAME, issue_session("u-mem"))
    # member can list but not invite
    assert client.get(f"/v1/orgs/{org_id}/members").status_code == 200
    assert client.post(f"/v1/orgs/{org_id}/members",
                       json={"email": "x@co.com", "role": "member"}).status_code == 403
