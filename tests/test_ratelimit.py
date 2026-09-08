"""The auth rate-limiter — fixed-window limits + lockout, with a fake Redis and dev-open off."""

from __future__ import annotations

import fakeredis
import pytest

from voiceobs import ratelimit


@pytest.fixture
def fake_redis(monkeypatch):
    # dev-open makes the limiter a no-op; turn it off so limits actually apply.
    monkeypatch.setattr(ratelimit, "dev_open", lambda: False)
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    ratelimit.set_client(r)
    yield r
    ratelimit.set_client(None)


def test_allow_blocks_past_limit(fake_redis):
    assert [ratelimit.allow("rl:login:1.2.3.4", 3, 60) for _ in range(5)] == \
        [True, True, True, False, False]
    # a different key has its own window
    assert ratelimit.allow("rl:login:9.9.9.9", 3, 60) is True


def test_lockout_counter(fake_redis):
    key = "lock:login:default:a@b.com"
    assert ratelimit.fail_count(key) == 0
    for _ in range(3):
        ratelimit.record_fail(key, 900)
    assert ratelimit.fail_count(key) == 3
    ratelimit.clear(key)
    assert ratelimit.fail_count(key) == 0


def test_fail_open_without_redis(monkeypatch):
    # no client + dev-open off → still allow (limiter must never break auth)
    monkeypatch.setattr(ratelimit, "dev_open", lambda: False)
    ratelimit.set_client(None)
    monkeypatch.setattr(ratelimit, "client", lambda: None)
    assert all(ratelimit.allow("rl:login:x", 1, 60) for _ in range(10))


def test_dev_open_is_noop(monkeypatch):
    monkeypatch.setattr(ratelimit, "dev_open", lambda: True)
    assert all(ratelimit.allow("rl:login:x", 1, 60) for _ in range(10))  # never limited in dev
