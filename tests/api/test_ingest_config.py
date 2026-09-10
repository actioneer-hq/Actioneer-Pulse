"""Token-authenticated self-registration: an agent's ingest token can register its own OTLP mapping
and storage config (no admin session), via /v1/ingest/*."""

from __future__ import annotations


def _agent_and_token(client, login_as) -> tuple[str, str]:
    login_as("default")  # owner: create the agent + mint its token
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    token = client.post(f"/v1/agents/{aid}/ingest-tokens", json={"name": "prod"}).json()["token"]
    return aid, token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_token_registers_otlp_mapping_and_bumps_version(client, login_as):
    aid, token = _agent_and_token(client, login_as)

    r = client.put("/v1/ingest/otlp-mapping", json={"expression": "{'header': header}"},
                   headers=_auth(token))
    assert r.status_code == 200 and r.json()["version"] == 1

    # second write upserts + bumps
    r2 = client.put("/v1/ingest/otlp-mapping", json={"expression": "{'header': $}"},
                    headers=_auth(token))
    assert r2.json()["version"] == 2

    # readable back through the admin endpoint (still logged in as owner)
    got = client.get(f"/v1/agents/{aid}/otlp-mapping").json()
    assert got["expression"] == "{'header': $}" and got["version"] == 2


def test_token_registers_storage_config(client, login_as):
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/storage-config", json={
        "enabled": True, "provider": "s3_compatible",
        "descriptor": {"bucket": "recordings", "list_prefix": "calls/"},
    }, headers=_auth(token))
    assert r.status_code == 200 and r.json()["enabled"] is True


def test_token_sets_agent_use_case(client, login_as):
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/agent-meta", json={
        "use_case": "outbound appointment reminders for dental clinics",
        "framework": "livekit", "language": "python",
    }, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["use_case"] == "outbound appointment reminders for dental clinics"


def test_agent_meta_requires_token(client):
    assert client.put("/v1/ingest/agent-meta", json={"use_case": "x"}).status_code == 401


def test_invalid_token_rejected(client):
    r = client.put("/v1/ingest/otlp-mapping", json={"expression": "{}"},
                   headers=_auth("vo_deadbeef_nope"))
    assert r.status_code == 401


def test_missing_token_rejected(client):
    r = client.put("/v1/ingest/otlp-mapping", json={"expression": "{}"})
    assert r.status_code == 401


def test_malformed_jsonata_rejected(client, login_as):
    _aid, token = _agent_and_token(client, login_as)
    r = client.put("/v1/ingest/otlp-mapping", json={"expression": "this is ( not valid"},
                   headers=_auth(token))
    assert r.status_code == 422
