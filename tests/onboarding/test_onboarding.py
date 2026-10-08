"""File onboarding: the pulse.calls.v1 format, utterances -> turns/latency, Sarvam STT shaping,
the local upload store, and an upload job end to end (ZIP + JSON -> analysed, judge-queued calls)."""

from __future__ import annotations

import io
import json
import wave
import zipfile

import numpy as np
import pytest
from sqlalchemy import select

from voiceobs.core.calculator import Calculator
from voiceobs.db.models import Agent, BackfillJob, Call, CallParams, Media, Turn
from voiceobs.onboarding import stt as stt_mod
from voiceobs.onboarding.format import ManifestError, Utterance, format_spec, parse_manifest
from voiceobs.onboarding.job import plan_calls
from voiceobs.onboarding.trace import build_trace, merge_blocks


def _wav(seconds: float, *, stereo: bool, speech: list[tuple[int, float, float]] = ()) -> bytes:
    sr = 8000
    a = np.zeros((int(sr * seconds), 2 if stereo else 1), dtype=np.int16)
    for ch, s, e in speech:  # loud tone where someone "speaks"
        t = np.arange(int(sr * s), int(sr * e))
        a[t, ch] = (3000 * np.sin(2 * np.pi * 220 * t / sr)).astype(np.int16)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(a.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())
    return b.getvalue()


# ── format ───────────────────────────────────────────────────────────────────────────
def test_manifest_parses():
    body = {"format": "pulse.calls.v1", "calls": [
        {"call_id": "a", "params": {"x": "1"},
         "transcript": [{"speaker": "customer", "text": "hi", "start": 2},
                        {"speaker": "agent", "text": "hello", "start": 0.5, "end": 1.5}]},
        {"call_id": "b", "params": {"x": "2"}}]}
    m = parse_manifest(json.dumps(body).encode())
    assert [u.speaker for u in m.calls[0].transcript] == ["agent", "customer"]  # sorted by start
    assert m.calls[1].transcript is None


def test_format_spec_is_driven_by_the_script():
    empty = format_spec(None)
    assert empty["has_script"] is False and empty["params"] == []
    spec = format_spec("Hi {{name}}, your {{ plan }} renews. {{name}}")
    assert spec["params"] == ["name", "plan"]
    assert spec["csv"]["columns"] == ["call_id", "name", "plan"]
    call = spec["json"]["schema"]["$defs"]["UploadCall"]
    assert call["properties"]["params"]["required"] == ["name", "plan"]
    assert "params" in call["required"]


def test_rejects_bad_json_and_duplicates():
    with pytest.raises(ManifestError, match="not valid JSON"):
        parse_manifest(b"{nope")
    dup = {"format": "pulse.calls.v1", "calls": [{"call_id": "a"}, {"call_id": "a"}]}
    with pytest.raises(ManifestError, match="duplicate call_id"):
        parse_manifest(json.dumps(dup).encode())
    wrong = {"format": "other", "calls": []}
    with pytest.raises(ManifestError) as e:
        parse_manifest(json.dumps(wrong).encode())
    assert any(err.startswith("format") for err in e.value.errors)


# ── utterances -> trace -> turns ─────────────────────────────────────────────────────
def test_trace_gives_turns_and_broad_latency():
    utt = [
        Utterance(speaker="agent", text="नमस्ते जी", start=0.4, end=3.0),
        Utterance(speaker="customer", text="हाँ", start=3.5, end=4.0),
        Utterance(speaker="customer", text="बोलिए", start=4.1, end=5.0),  # merged with the above
        Utterance(speaker="agent", text="offer", start=5.8, end=9.0),
    ]
    assert [b.speaker for b in merge_blocks(utt)] == ["agent", "customer", "agent"]
    analysis = Calculator().analyze(build_trace("c1", utt, started_at=None, duration_s=10.0),
                                    None, audio_enabled=False)
    with_caller = [t for t in analysis.turns if t.transcript]
    assert with_caller[0].transcript == "हाँ बोलिए"
    assert with_caller[0].llm_spoken == "offer"
    assert with_caller[0].response_latency_ms == pytest.approx(800, abs=1)  # 5.0 -> 5.8


# ── STT shaping ──────────────────────────────────────────────────────────────────────
def test_stereo_split_assigns_the_talkative_side_to_the_agent(monkeypatch):
    data = _wav(12, stereo=True, speech=[(1, 0.5, 6.0), (0, 6.8, 8.0)])
    samples, sr = stt_mod.read_wav(data)
    monkeypatch.setattr(stt_mod, "_rest_transcribe", lambda cfg, audio, client: "text")
    out = stt_mod.transcribe_stereo(stt_mod.SttConfig(api_key="k"), samples, sr)
    assert [u.speaker for u in out] == ["agent", "customer"]
    assert out[0].start < 0.6 and out[1].start == pytest.approx(6.65, abs=0.1)


def test_diarized_entries_map_speakers():
    entries = [
        {"transcript": "hello ji offer", "start_time_seconds": 0, "end_time_seconds": 6, "speaker_id": "1"},
        {"transcript": "haan", "start_time_seconds": 6.5, "end_time_seconds": 7, "speaker_id": "0"},
    ]
    out = stt_mod.entries_to_utterances(entries)
    assert [(u.speaker, u.text) for u in out] == [("agent", "hello ji offer"), ("customer", "haan")]


# ── local store ──────────────────────────────────────────────────────────────────────
def test_upload_uri_cannot_escape_root(tmp_path, monkeypatch):
    from voiceobs.storage.drivers import local

    monkeypatch.setenv("VOICEOBS_UPLOAD_DIR", str(tmp_path))
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.wav").write_bytes(b"RIFF")
    assert local.LocalDriver().fetch_bytes("upload://a/x.wav", None) == b"RIFF"
    for bad in ("upload://../etc/passwd", "upload:///etc/passwd", "upload://a/../../x"):
        with pytest.raises(ValueError):
            local.path_for(bad)


# ── planning ─────────────────────────────────────────────────────────────────────────
def test_plan_pairs_json_entries_with_audio(tmp_path):
    m = parse_manifest(json.dumps({"format": "pulse.calls.v1", "calls": [
        {"call_id": "a1"}, {"call_id": "b2", "audio_file": "rec-b.mp3"},
        {"call_id": "c3"},  # no audio, no transcript -> error
    ]}).encode())
    audio = {n: tmp_path / n for n in ("a1.wav", "rec-b.mp3", "extra.wav")}
    plans = {p.call_id: p for p in plan_calls(audio, m.calls)}
    assert plans["a1"].audio.name == "a1.wav"
    assert plans["b2"].audio.name == "rec-b.mp3"
    assert plans["c3"].error
    assert plans["extra"].spec is None  # audio-only file becomes its own call


# ── end to end ───────────────────────────────────────────────────────────────────────
def test_upload_job_end_to_end(tmp_path, db_sessionmaker, bus, monkeypatch):
    from voiceobs.config import get_config
    from voiceobs.worker.backfill import run_job

    monkeypatch.setenv("VOICEOBS_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("VOICEOBS_SARVAM_API_KEY", "k")
    cfg = get_config()
    monkeypatch.setattr(stt_mod, "_rest_transcribe", lambda c, audio, client: "हाँ जी")
    job_dir = tmp_path / "org" / "ag1" / "job1"
    job_dir.mkdir(parents=True)
    with zipfile.ZipFile(job_dir / "calls.zip", "w") as z:
        z.writestr("calls/with-json.wav", _wav(8, stereo=True))
        z.writestr("calls/stt-me.wav", _wav(10, stereo=True, speech=[(1, 0.5, 6), (0, 7, 8)]))
        z.writestr("__MACOSX/._junk.wav", b"x")
        z.writestr("notes.txt", b"ignore me")
    manifest = {"format": "pulse.calls.v1", "calls": [{
        "call_id": "with-json", "params": {"first_name": "Mamta"},
        "transcript": [{"speaker": "agent", "text": "नमस्ते", "start": 0.2, "end": 2.0},
                       {"speaker": "customer", "text": "हाँ", "start": 2.5, "end": 3.0},
                       {"speaker": "agent", "text": "offer", "start": 3.4, "end": 6.0}],
    }]}
    (job_dir / "manifest.json").write_text(json.dumps(manifest))

    with db_sessionmaker() as db:
        db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
        job = BackfillJob(org_id="default", agent_id="ag1", source="upload", status="queued",
                          options={"dir": str(job_dir), "manifest": True})
        db.add(job)
        db.commit()
        run_job(db, job, "default")
        assert job.status == "done", job.error
        assert (job.total, job.completed, job.failed) == (2, 2, 0)

        calls = {c.external_call_id: c for c in db.scalars(select(Call))}
        assert set(calls) == {"with-json", "stt-me"}
        c = calls["with-json"]
        assert (c.source, c.status) == ("upload", "computed")
        assert c.duration_s == pytest.approx(8.0)
        turns = db.scalars(select(Turn).where(Turn.call_id == c.id)).all()
        assert any(t.caller_transcript == "हाँ" and t.response_latency_ms == pytest.approx(400, abs=1)
                   for t in turns)
        media = db.scalar(select(Media).where(Media.call_id == c.id))
        assert media.uri == "upload://org/ag1/job1/audio/with-json.wav" and media.channels == 2
        assert db.scalar(select(CallParams.params).where(CallParams.call_key == "with-json")) == \
            {"first_name": "Mamta"}
        stt_turns = db.scalars(select(Turn).where(Turn.call_id == calls["stt-me"].id)).all()
        assert any(t.caller_transcript == "हाँ जी" for t in stt_turns)

    judged = {json.loads(r.value)["call_id"] for r in bus.drain(cfg.kafka_topic_judge_backfill)}
    assert judged == {"with-json", "stt-me"}


def _zip(*names: str) -> bytes:
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        for n in names:
            zf.writestr(n, _wav(1, stereo=True))
    return z.getvalue()


@pytest.fixture
def project(authed_client, db_sessionmaker, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICEOBS_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("VOICEOBS_SARVAM_API_KEY", "k")
    with db_sessionmaker() as db:
        db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
        db.commit()
    return authed_client


def _post(client, zip_bytes, *, csv=None, js=None):
    files = {"audio": ("calls.zip", zip_bytes, "application/zip")} if zip_bytes is not None else {}
    if csv is not None:
        files["params_csv"] = ("params.csv", csv, "text/csv")
    if js is not None:
        files["manifest"] = ("calls.json", json.dumps(js), "application/json")
    return client.post("/v1/agents/ag1/uploads", files=files)


def test_upload_json_mode(project, tmp_path):
    body = {"format": "pulse.calls.v1", "script": "Hi {{first_name}}", "calls": [
        {"call_id": "a", "params": {"first_name": "Mamta"},
         "transcript": [{"speaker": "agent", "text": "Hi Mamta", "start": 0.1}]}]}
    r = _post(project, _zip("a.wav"), js=body)
    assert r.status_code == 201, r.text
    assert r.json()["params"] == ["first_name"] and r.json()["transcribe"] == 0
    job = project.get(f"/v1/backfill/{r.json()['id']}").json()
    assert job["status"] == "queued" and job["source"] == "upload"
    assert project.get("/v1/agents/ag1/script").json()["text"] == "Hi {{first_name}}"


def test_upload_csv_mode_uses_project_script(project, tmp_path):
    project.put("/v1/agents/ag1/script", json={"text": "नमस्ते {{first_name}} — {{plan}}"})
    r = _post(project, _zip("x1.wav", "x2.wav"),
              csv="call_id,first_name,plan\nx1,Jagdish,Stocks\nx2,Mamta,Options\n")
    assert r.status_code == 201, r.text
    assert r.json() == {**r.json(), "calls": 2, "params": ["first_name", "plan"], "transcribe": 2}
    saved = next(tmp_path.rglob("manifest.json"))
    m = parse_manifest(saved.read_bytes())
    assert {c.call_id: c.params for c in m.calls}["x2"] == {"first_name": "Mamta", "plan": "Options"}


def test_upload_rejections(project):
    project.put("/v1/agents/ag1/script", json={"text": "Hi {{first_name}} {{plan}}"})
    zip2 = _zip("x1.wav", "x2.wav")
    # a ZIP alone, or both side files
    assert _post(project, zip2).status_code == 422
    assert _post(project, zip2, csv="call_id\nx1\n",
                 js={"format": "pulse.calls.v1", "calls": []}).status_code == 422
    # missing placeholder values + an audio file with no row
    r = _post(project, zip2, csv="call_id,first_name\nx1,Jagdish\n")
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert any("missing `plan`" in e for e in errs)
    assert any("no row" in e and "x2.wav" in e for e in errs)
    # a row with no audio
    r = _post(project, _zip("x1.wav"), csv="call_id,first_name,plan\nx1,A,B\nghost,C,D\n")
    assert any("no audio file" in e and "ghost" in e for e in r.json()["detail"]["errors"])
    # invalid JSON
    assert _post(project, zip2, js={"format": "x"}).status_code == 422


def test_upload_needs_a_script(project):
    r = _post(project, _zip("x1.wav"), csv="call_id,first_name\nx1,A\n")
    assert r.status_code == 422 and "no script" in r.json()["detail"]


def test_format_uses_project_placeholders(project):
    project.put("/v1/agents/ag1/script", json={"text": "{{customer}} owes {{amount}}"})
    f = project.get("/v1/uploads/format", params={"agent_id": "ag1"}).json()
    assert f["has_script"] and f["params"] == ["customer", "amount"]
    assert f["csv"]["columns"] == ["call_id", "customer", "amount"]
    assert f["json"]["schema"]["$defs"]["UploadCall"]["properties"]["params"]["required"] == \
        ["customer", "amount"]


def test_json_upload_without_audio(project, tmp_path, db_sessionmaker, bus):
    from voiceobs.worker.backfill import run_job

    body = {"format": "pulse.calls.v1", "script": "Hi {{first_name}}", "calls": [
        {"call_id": "t1", "params": {"first_name": "Mamta"},
         "transcript": [{"speaker": "agent", "text": "Hi Mamta", "start": 0.1, "end": 1.0},
                        {"speaker": "customer", "text": "haan", "start": 1.4, "end": 2.0}]}]}
    r = _post(project, None, js=body)
    assert r.status_code == 201, r.text
    # a CSV still needs the audio (Pulse transcribes it); a JSON call without a transcript needs it too
    assert "needs the audio ZIP" in _post(project, None, csv="call_id,first_name\nx1,A\n").json()["detail"]
    no_text = {"format": "pulse.calls.v1", "calls": [{"call_id": "t2", "params": {"first_name": "A"}}]}
    errs = _post(project, None, js=no_text).json()["detail"]["errors"]
    assert any("no transcript" in e and "t2" in e for e in errs)

    with db_sessionmaker() as db:  # the job runs with no ZIP: transcript only, no audio player
        job = db.get(BackfillJob, r.json()["id"])
        assert job.options["audio"] is False
        run_job(db, job, "default")
        assert job.status == "done" and (job.completed, job.failed) == (1, 0), job.error
        call = db.scalar(select(Call).where(Call.external_call_id == "t1"))
        assert call.status == "computed" and db.scalar(select(Media).where(Media.call_id == call.id)) is None


def test_deleting_a_project_deletes_its_calls_and_frees_their_ids(project, db_sessionmaker):
    from voiceobs.db.models import Judgment
    from voiceobs.worker.backfill import run_job

    body = {"format": "pulse.calls.v1", "script": "Hi {{first_name}}", "calls": [
        {"call_id": "t1", "params": {"first_name": "A"},
         "transcript": [{"speaker": "agent", "text": "Hi", "start": 0.1}]}]}
    with db_sessionmaker() as db:
        run_job(db, db.get(BackfillJob, _post(project, None, js=body).json()["id"]), "default")
        call = db.scalar(select(Call).where(Call.external_call_id == "t1"))
        db.add(Judgment(call_id=call.id, status="ok"))
        db.commit()
    assert project.delete("/v1/agents/ag1").status_code == 200
    with db_sessionmaker() as db:
        assert db.scalar(select(Call)) is None and db.scalar(select(Judgment)) is None
        db.add(Agent(id="ag1", org_id="default", name="Bot", slug="bot"))
        db.commit()
    with db_sessionmaker() as db:   # the same calls upload again
        job = db.get(BackfillJob, _post(project, None, js=body).json()["id"])
        run_job(db, job, "default")
        assert (job.completed, job.failed) == (1, 0), job.error


def test_upload_reclaims_calls_left_by_a_deleted_project(project, db_sessionmaker):
    from voiceobs.worker.backfill import run_job

    with db_sessionmaker() as db:   # an orphan: its project row is gone
        db.add(Call(external_call_id="t1", agent_id="gone-agent", source="upload", environment="prod",
                    status="computed"))
        db.commit()
    body = {"format": "pulse.calls.v1", "script": "Hi {{first_name}}", "calls": [
        {"call_id": "t1", "params": {"first_name": "A"},
         "transcript": [{"speaker": "agent", "text": "Hi", "start": 0.1}]}]}
    with db_sessionmaker() as db:
        job = db.get(BackfillJob, _post(project, None, js=body).json()["id"])
        run_job(db, job, "default")
        assert (job.completed, job.failed) == (1, 0), job.error
        assert db.scalar(select(Call.agent_id).where(Call.external_call_id == "t1")) == "ag1"


def test_upload_stops_when_its_project_is_deleted_mid_run(project, db_sessionmaker, monkeypatch):
    from voiceobs.onboarding import job as job_mod
    from voiceobs.worker.backfill import run_job

    calls = [{"call_id": f"t{i}", "params": {"first_name": "A"},
              "transcript": [{"speaker": "agent", "text": "Hi", "start": 0.1}]} for i in range(3)]
    body = {"format": "pulse.calls.v1", "script": "Hi {{first_name}}", "calls": calls}
    job_id = _post(project, None, js=body).json()["id"]
    real = job_mod._analyse

    def analyse_then_delete(db, *a, **k):   # the project is deleted right after the first call
        out = real(db, *a, **k)
        db.query(BackfillJob).filter(BackfillJob.id == job_id).delete()
        return out

    monkeypatch.setattr(job_mod, "_analyse", analyse_then_delete)
    with db_sessionmaker() as db:
        run_job(db, db.get(BackfillJob, job_id), "default")
        assert len(db.scalars(select(Call)).all()) == 1   # stopped instead of ingesting the rest
