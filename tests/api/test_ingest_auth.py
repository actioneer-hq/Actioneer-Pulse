"""Ingest authentication: a per-agent token routes the call to its org+agent (authoritative
over span/header tenant); no token is refused unless dev-open."""

from __future__ import annotations

from sqlalchemy import select

from tests.fixtures.vas_call import sample_call
from voiceobs.db.models import Call


def _mint_token(client, login_as) -> tuple[str, str]:
    login_as("acme")  # owner of a fresh org
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    tok = client.post(f"/v1/agents/{aid}/ingest-tokens", json={}).json()["token"]
    return aid, tok


def test_token_routes_call_over_span_tenant(client, login_as, db_sessionmaker):
    aid, tok = _mint_token(client, login_as)
    # sample_call carries voice.tenant_id = vastu-hfc, but the acme token is authoritative
    r = client.post("/v1/traces", json=sample_call(),
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert call.tenant_id == "acme"
        assert call.agent_id == aid


def test_bad_token_is_401(client):
    r = client.post("/v1/traces", json=sample_call(),
                    headers={"Authorization": "Bearer vo_deadbeef_nope"})
    assert r.status_code == 401


def test_tokenless_ingest_requires_dev_open(client, monkeypatch):
    monkeypatch.delenv("VOICEOBS_DEV_OPEN", raising=False)  # turn dev-open OFF
    assert client.post("/v1/traces", json=sample_call()).status_code == 401


def test_dev_open_tokenless_falls_back_to_span_tenant(client, db_sessionmaker):
    # autouse dev-open is on → token-less ingest lands under the span tenant, no agent
    assert client.post("/v1/traces", json=sample_call()).status_code == 200
    with db_sessionmaker() as db:
        call = db.scalars(select(Call)).one()
        assert call.tenant_id == "vastu-hfc"
        assert call.agent_id is None
