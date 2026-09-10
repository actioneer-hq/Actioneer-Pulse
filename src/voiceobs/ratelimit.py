"""Redis-backed abuse protection for the auth endpoints — fixed-window rate limits + per-account
login lockout. Deliberately narrow: this is NOT for chat/LLM (BYO key → concurrency is fine).

Fail-open and dev-safe: a no-op under dev-open and when `redis_url` is unset, and any Redis error is
swallowed (auth must never hard-break because the limiter is down). Tests inject a fake client via
`set_client`."""

from __future__ import annotations

import logging

from voiceobs.auth.env import dev_open
from voiceobs.config import get_config

log = logging.getLogger(__name__)

_client = None
_client_url: str | None = None
_override = None  # test hook


def set_client(client) -> None:
    """Test hook — inject a fake Redis (e.g. fakeredis). Pass None to reset."""
    global _override
    _override = client


def client():
    """A cached Redis client for the configured url, or None (limiter disabled → fail-open)."""
    global _client, _client_url
    if _override is not None:
        return _override
    if dev_open():  # dev is fully fail-open — never import/require redis, even if redis_url is set
        return None
    url = get_config().redis_url
    if not url:
        return None
    if _client is None or _client_url != url:
        import redis
        _client = redis.from_url(url, decode_responses=True)
        _client_url = url
    return _client


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — limiter must never break the request
        log.warning("ratelimit: redis error (%s); failing open", e)
        return default


def allow(key: str, limit: int, window_s: int) -> bool:
    """Fixed-window counter. True = under the limit (allowed). Fail-open (no Redis / dev-open → True)."""
    if dev_open():
        return True
    c = client()
    if c is None:
        return True

    def run() -> bool:
        n = c.incr(key)
        if n == 1:
            c.expire(key, window_s)
        return n <= limit

    return _safe(run, True)


def record_fail(key: str, window_s: int) -> None:
    """Increment a per-account failure counter (for lockout), with a rolling TTL."""
    c = client()
    if c is None:
        return
    _safe(lambda: (c.incr(key), c.expire(key, window_s)), None)


def fail_count(key: str) -> int:
    c = client()
    if c is None:
        return 0
    return _safe(lambda: int(c.get(key) or 0), 0)


def clear(key: str) -> None:
    c = client()
    if c is not None:
        _safe(lambda: c.delete(key), None)
