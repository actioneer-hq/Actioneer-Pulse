"""Read endpoint tests — list, detail, metric-defs."""

from __future__ import annotations

from tests.adapters.fixtures.vas_call import sample_call


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_and_filter(client):
    client.post("/v1/traces", json=sample_call())
    assert len(client.get("/v1/calls").json()["items"]) == 1
    assert len(client.get("/v1/calls?status=awaiting_media").json()["items"]) == 1
    assert client.get("/v1/calls?status=ingested").json()["items"] == []


def test_detail_shape(client):
    client.post("/v1/traces", json=sample_call())
    d = client.get("/v1/calls/c1").json()
    assert d["call"]["id"] == "c1"
    assert d["turns"] == []  # empty until the worker runs
    assert d["metrics"] == []
    assert "versions" in d


def test_detail_404(client):
    assert client.get("/v1/calls/nope").status_code == 404


def test_metric_defs(client):
    defs = client.get("/v1/metric-defs").json()
    names = {d["name"] for d in defs}
    assert {"capture_coverage", "llm_ttft_ms"} <= names
    cov = next(d for d in defs if d["name"] == "capture_coverage")
    assert cov["higher_is_better"] is True
