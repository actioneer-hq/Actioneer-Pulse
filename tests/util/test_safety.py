"""Security primitives: ReDoS-bounded search, bounded gunzip, SSRF endpoint guard."""

from __future__ import annotations

import gzip

import pytest

from voiceobs.util.safety import (
    EndpointBlocked,
    PayloadTooLarge,
    assert_public_endpoint,
    bounded_gunzip,
    safe_search,
    validate_pattern,
)


def test_safe_search_matches_normally():
    m = safe_search(r"^calls/([^/]+)/events\.json$", "calls/c-1/events.json")
    assert m and m.group(1) == "c-1"


def test_safe_search_times_out_on_catastrophic_pattern():
    # classic exponential-backtracking pattern against a non-matching long input
    evil = "(a+)+$"
    payload = "a" * 60 + "!"
    # returns None (treated as no-match) rather than hanging the caller
    assert safe_search(evil, payload, timeout=0.05) is None


def test_safe_search_rejects_overlong_key():
    assert safe_search(r"x", "x" * 5000) is None  # beyond MAX_KEY_LEN → skipped


def test_validate_pattern_rejects_overlong_and_invalid():
    with pytest.raises(ValueError):
        validate_pattern("a" * 1000, "p")
    with pytest.raises(ValueError):
        validate_pattern("(", "p")
    assert validate_pattern(r"^calls/(.+)$", "p")


def test_bounded_gunzip_allows_within_limit():
    raw = gzip.compress(b"hello world" * 10)
    assert bounded_gunzip(raw, 10_000) == b"hello world" * 10


def test_bounded_gunzip_stops_a_bomb():
    bomb = gzip.compress(b"\x00" * (5 * 1024 * 1024))  # 5 MiB of zeros, tiny compressed
    with pytest.raises(PayloadTooLarge):
        bounded_gunzip(bomb, 1024)  # ceiling far below the decompressed size


def test_assert_public_endpoint_blocks_loopback_and_metadata():
    for url in ("http://127.0.0.1:9000", "http://localhost/x", "http://169.254.169.254/latest"):
        with pytest.raises(EndpointBlocked):
            assert_public_endpoint(url, enabled=True)


def test_assert_public_endpoint_noop_when_disabled():
    assert_public_endpoint("http://127.0.0.1:9000", enabled=False)  # opt-out for self-host


def test_assert_public_endpoint_allows_public(monkeypatch):
    # stub DNS so the test never touches the network
    monkeypatch.setattr("voiceobs.util.safety.socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert_public_endpoint("https://storage.example.com", enabled=True)  # resolves public
    assert_public_endpoint(None, enabled=True)  # no endpoint → nothing to check
