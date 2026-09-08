"""Azure Blob driver — uri parsing + descriptor-driven listing (SDK mocked, no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from voiceobs.storage.drivers.azure import AzureDriver, _parse


def test_parse_azblob_uri():
    assert _parse("azblob://recordings/calls/c1/audio.wav") == ("recordings", "calls/c1/audio.wav")


def test_azure_list_from_descriptor(monkeypatch):
    class _Blob:
        def __init__(self, name):
            self.name = name
            self.last_modified = datetime(2026, 8, 1, tzinfo=UTC)

    class _Container:
        def list_blobs(self, name_starts_with):
            assert name_starts_with == "calls/"
            return [_Blob("calls/c1/audio.wav"), _Blob("calls/c2/audio.wav")]

    class _Service:
        def get_container_client(self, container):
            assert container == "recordings"
            return _Container()

    monkeypatch.setattr("voiceobs.storage.drivers.azure._service_client", lambda creds: _Service())
    got = AzureDriver().list({"bucket": "recordings", "list_prefix": "calls/"}, {})
    assert [u for u, _ in got] == [
        "azblob://recordings/calls/c1/audio.wav",
        "azblob://recordings/calls/c2/audio.wav",
    ]
