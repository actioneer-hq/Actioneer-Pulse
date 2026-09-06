"""Agent guardrails: versioning, hash dedup, admin gating (mirrors agent scripts)."""

from __future__ import annotations


def test_set_and_version_bump(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    v1 = client.put(f"/v1/agents/{aid}/guardrails",
                    json={"text": "Stay on script."}).json()
    assert v1["version"] == 1 and len(v1["sha256"]) == 64
    v2 = client.put(f"/v1/agents/{aid}/guardrails",
                    json={"text": "Verify the caller before any DB lookup."}).json()
    assert v2["version"] == 2 and v2["sha256"] != v1["sha256"]
    hist = client.get(f"/v1/agents/{aid}/guardrails/versions").json()["items"]
    assert [h["version"] for h in hist] == [2, 1]
    assert [h["active"] for h in hist] == [True, False]


def test_identical_text_no_new_version(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents",
                      json={"name": "Bot", "guardrails": "Do not go off purpose."}).json()["id"]
    same = client.put(f"/v1/agents/{aid}/guardrails",
                      json={"text": "Do not go off purpose."}).json()
    assert same["version"] == 1  # unchanged text → still v1
    assert len(client.get(f"/v1/agents/{aid}/guardrails/versions").json()["items"]) == 1


def test_get_guardrails_returns_text(client, login_as):
    login_as("default")
    text = "Always verify the caller.\nNever leave the script."
    aid = client.post("/v1/agents", json={"name": "Bot", "guardrails": text}).json()["id"]
    got = client.get(f"/v1/agents/{aid}/guardrails").json()
    assert got["text"] == text and got["version"] == 1


def test_get_guardrails_empty_when_unset(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    got = client.get(f"/v1/agents/{aid}/guardrails").json()
    assert got == {"version": None, "text": None}


def test_set_requires_admin(client, login_as):
    login_as("default")
    aid = client.post("/v1/agents", json={"name": "Bot"}).json()["id"]
    login_as("default", role="viewer")
    assert client.put(f"/v1/agents/{aid}/guardrails", json={"text": "x"}).status_code == 403
