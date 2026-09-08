"""BYO diarization client parsing + role assignment."""

from __future__ import annotations

import voiceobs.diarize.client as dc
from voiceobs.diarize.client import Diarization, DiarizeConfig, Segment, diarize
from voiceobs.diarize.roles import assign_roles, to_utterances


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_diarize_none_config_and_empty_wav():
    assert diarize(None, b"wav") is None
    assert diarize(DiarizeConfig("https://x", "m"), b"") is None


def test_diarize_parses_segments_and_confidence(monkeypatch):
    body = {
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"start": 1.2, "end": 2.0, "speaker": "SPEAKER_01"},
            {"bad": "no end"},  # skipped
        ],
        "confidence": 0.82,
    }
    monkeypatch.setattr(dc.httpx, "post", lambda *a, **k: _Resp(body))
    out = diarize(DiarizeConfig("https://x/", "pyannote", "key"), b"RIFFwav")
    assert out is not None
    assert len(out.segments) == 2
    assert out.confidence == 0.82
    assert out.speakers() == ["SPEAKER_00", "SPEAKER_01"]


def test_diarize_retries_then_none(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(dc.httpx, "post", boom)
    assert diarize(DiarizeConfig("https://x", "m"), b"wav") is None


def test_assign_roles_first_speaker_is_agent():
    diar = Diarization(segments=[
        Segment(0.0, 1.0, "A"), Segment(1.1, 2.0, "B"), Segment(2.1, 3.0, "A"),
    ])
    roles = assign_roles(diar)
    assert roles == {"A": "agent", "B": "caller"}


def test_assign_roles_override_flips():
    diar = Diarization(segments=[Segment(0.0, 1.0, "A"), Segment(1.1, 2.0, "B")])
    assert assign_roles(diar, agent_speaker="B") == {"A": "caller", "B": "agent"}


def test_to_utterances_maps_roles_in_time_order():
    diar = Diarization(segments=[Segment(1.1, 2.0, "B"), Segment(0.0, 1.0, "A")])
    utts = to_utterances(diar, {"A": "agent", "B": "caller"})
    assert [(u.channel, u.t_start) for u in utts] == [("agent", 0.0), ("caller", 1.1)]
