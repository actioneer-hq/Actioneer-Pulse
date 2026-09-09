"""Audio-native chat tool: opt-in registration, scope-guard prompt, sub-call message, dispatch."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import voiceobs.chat.audio_native as an
from voiceobs.chat import tools
from voiceobs.chat.schema_doc import build_system_prompt
from voiceobs.db.models import Call, Media, Membership


def _enable(monkeypatch):
    monkeypatch.setenv("VOICEOBS_AUDIO_NATIVE_API_KEY", "sk-audio")


# ── tool registration is opt-in ──────────────────────────────────────────────
def test_tool_absent_when_disabled():
    names = [s["function"]["name"] for s in tools.schemas(audio_native=False)]
    assert names == ["execute_sql"]


def test_tool_present_when_enabled_global_requires_call_id():
    schemas = tools.schemas(audio_native=True, bound_call=False)
    audio = next(s for s in schemas if s["function"]["name"] == "audio_native_llm")
    assert set(audio["function"]["parameters"]["required"]) == {"prompt", "call_id"}


def test_tool_present_when_enabled_percall_prompt_only():
    schemas = tools.schemas(audio_native=True, bound_call=True)
    audio = next(s for s in schemas if s["function"]["name"] == "audio_native_llm")
    assert audio["function"]["parameters"]["required"] == ["prompt"]


# ── scope guard appears only when enabled ────────────────────────────────────
def test_scope_guard_only_when_enabled():
    assert "audio_native_llm" not in build_system_prompt("p", audio_native=False)
    p = build_system_prompt("p", audio_native=True)
    assert "audio_native_llm" in p and "NEVER use it" in p


# ── analyze() builds the input_audio multimodal message ──────────────────────
def test_analyze_builds_input_audio_message(db_sessionmaker, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(an, "fetch_bytes", lambda uri, creds=None: b"RIFF-caller" if "caller" in uri else b"RIFF-agent")
    captured = {}

    def fake_complete(resolved, messages):
        captured["resolved"], captured["messages"] = resolved, messages
        msg = SimpleNamespace(content="the caller sounds calm")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr(an.gateway, "complete", fake_complete)

    with db_sessionmaker() as db:
        call = Call(external_call_id="c1", source="x", environment="prod", status="ingested")
        db.add(call)
        db.flush()
        db.add(Media(call_id=call.id, kind="audio_caller", uri="s3://b/c1/caller.wav"))
        db.add(Media(call_id=call.id, kind="audio_agent", uri="s3://b/c1/agent.wav"))
        db.flush()
        out = an.analyze(db, call, "how does the caller sound?")

    assert out == "the caller sounds calm"
    # system prompt is the AUDIO_NATIVE role prompt; user content carries two input_audio parts
    assert captured["resolved"].role.value == "audio_native"
    user = captured["messages"][1]
    parts = [p["type"] for p in user["content"]]
    assert parts == ["text", "input_audio", "input_audio"]
    assert user["content"][1]["input_audio"]["data"] == base64.b64encode(b"RIFF-caller").decode()


def test_analyze_no_audio_returns_graceful_string(db_sessionmaker, monkeypatch):
    _enable(monkeypatch)
    with db_sessionmaker() as db:
        call = Call(external_call_id="c2", source="x", environment="prod", status="ingested")
        db.add(call)
        db.flush()
        out = an.analyze(db, call, "anything?")
    assert "no audio" in out


def test_analyze_disabled_returns_string(db_sessionmaker):
    with db_sessionmaker() as db:
        call = Call(external_call_id="c3", source="x", environment="prod", status="ingested")
        db.add(call)
        db.flush()
        assert "no audio-native model configured" in an.analyze(db, call, "q")


# ── dispatch through tools.run ───────────────────────────────────────────────
def test_run_dispatches_bound_call(db_sessionmaker, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(an, "analyze", lambda db, call, prompt: f"analyzed {call.external_call_id}")
    with db_sessionmaker() as db:
        call = Call(external_call_id="cb", source="x", environment="prod", status="ingested")
        db.add(call)
        db.flush()
        mem = Membership(org_id="default", user_id="u1", role="owner")
        out = tools.run(db, mem, "audio_native_llm", {"prompt": "tone?"}, call=call)
    assert out == {"analysis": "analyzed cb"}


def test_run_global_requires_call_id(db_sessionmaker, monkeypatch):
    _enable(monkeypatch)
    with db_sessionmaker() as db:
        mem = Membership(org_id="default", user_id="u1", role="owner")
        assert "call_id is required" in tools.run(db, mem, "audio_native_llm", {"prompt": "x"})["error"]
