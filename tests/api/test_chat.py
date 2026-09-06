"""Chat: conversation CRUD (RBAC-scoped) + the SSE stream against a mocked agent."""

from __future__ import annotations

import json


def test_conversation_crud_and_scoping(client, login_as):
    login_as("default")
    cid = client.post("/v1/chat/conversations").json()["id"]
    assert cid
    assert cid in {c["id"] for c in client.get("/v1/chat/conversations").json()["items"]}
    # another org can't see or fetch it
    login_as("other")
    assert cid not in {c["id"] for c in client.get("/v1/chat/conversations").json()["items"]}
    assert client.get(f"/v1/chat/conversations/{cid}").status_code == 404
    # owner can delete
    login_as("default")
    assert client.delete(f"/v1/chat/conversations/{cid}").json()["status"] == "ok"


def test_stream_emits_events_and_persists(client, login_as, db_sessionmaker, monkeypatch):
    login_as("default")
    monkeypatch.setenv("VOICEOBS_GLOBAL_CHAT_API_KEY", "k")  # activates the global_chat role
    cid = client.post("/v1/chat/conversations").json()["id"]

    # mock the agent so no network: one tool round then a two-token answer
    import voiceobs.chat as chatpkg

    def fake_run(db, mem, resolved, history, text):
        yield {"type": "tool_call", "name": "search_calls", "args": {"limit": 5}}
        yield {"type": "tool_result", "name": "search_calls", "summary": "3 calls"}
        yield {"type": "token", "text": "You have "}
        yield {"type": "token", "text": "3 calls."}
        yield {"type": "done", "content": "You have 3 calls.",
               "steps": [{"name": "search_calls", "summary": "3 calls"}]}
    monkeypatch.setattr(chatpkg, "run", fake_run)

    r = client.post(f"/v1/chat/conversations/{cid}/stream", json={"text": "how many calls?"})
    assert r.status_code == 200
    events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
    types = [e["type"] for e in events]
    assert types == ["tool_call", "tool_result", "token", "token", "done"]

    # persisted: user + assistant, assistant carries steps; title auto-set
    convo = client.get(f"/v1/chat/conversations/{cid}").json()
    assert convo["title"] == "how many calls?"
    roles = [m["role"] for m in convo["messages"]]
    assert roles == ["user", "assistant"]
    assert convo["messages"][1]["content"] == "You have 3 calls."
    assert convo["messages"][1]["steps"][0]["name"] == "search_calls"


def test_stream_without_llm_config_errors_gracefully(client, login_as):
    login_as("default")
    cid = client.post("/v1/chat/conversations").json()["id"]
    r = client.post(f"/v1/chat/conversations/{cid}/stream", json={"text": "hi"})
    assert r.status_code == 200  # SSE always 200; the error rides in the stream
    events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
    assert events[-1]["type"] == "error" and "not configured" in events[-1]["error"]
