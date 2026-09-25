"""Security primitives: bounded regex matching, bounded decompression, SSRF endpoint guard.

Kept dependency-free of the rest of voiceobs so any layer can import it. All three defend
against attacker-controlled input reaching an unbounded operation (ReDoS, decompression bombs,
server-side requests to internal endpoints)."""

from __future__ import annotations

import ipaddress
import logging
import socket
import zlib
from urllib.parse import urlparse

import regex

log = logging.getLogger(__name__)

MAX_PATTERN_LEN = 512  # tenant-supplied selector/key regexes may not exceed this
MAX_KEY_LEN = 4096  # object keys longer than this are never matched (bounds worst-case work)
_SEARCH_TIMEOUT_S = 0.1  # per-match wall-clock ceiling — a backtracking pattern can't hang a worker


class PayloadTooLarge(Exception):
    """A body or decompressed stream exceeded its configured ceiling."""


class EndpointBlocked(Exception):
    """A URL resolved to a non-public address and internal-fetch blocking is on."""


def safe_search(pattern: str | regex.Pattern, key: str, *, timeout: float = _SEARCH_TIMEOUT_S):
    """`.search` with a wall-clock timeout so a catastrophic-backtracking (ReDoS) pattern from a
    tenant manifest/descriptor can't pin a worker. Returns the match or None; a timeout is treated
    as no-match and logged (the object is skipped, the sweep continues)."""
    if len(key) > MAX_KEY_LEN:
        return None
    compiled = pattern if isinstance(pattern, regex.Pattern) else regex.compile(pattern)
    try:
        return compiled.search(key, timeout=timeout)
    except TimeoutError:
        log.warning("regex match timed out (>%.3fs) — treating as no-match", timeout)
        return None


def validate_pattern(pattern: str, field: str) -> str:
    """Reject over-long tenant regexes at write time (they are compiled+run per object key)."""
    if not isinstance(pattern, str) or len(pattern) > MAX_PATTERN_LEN:
        raise ValueError(f"{field} must be a string of at most {MAX_PATTERN_LEN} characters")
    try:
        regex.compile(pattern)
    except regex.error as e:
        raise ValueError(f"{field} is not a valid regex: {e}") from e
    return pattern


def bounded_gunzip(raw: bytes, limit: int) -> bytes:
    """Decompress gzip `raw`, raising PayloadTooLarge once output would exceed `limit` bytes.
    Incremental (zlib.decompressobj) so a decompression bomb is stopped early, not after it has
    already allocated gigabytes."""
    dec = zlib.decompressobj(wbits=47)  # 47 = accept gzip or zlib headers
    out = bytearray()
    for start in range(0, len(raw), 65536):
        chunk = dec.decompress(raw[start : start + 65536], limit - len(out) + 1)
        out.extend(chunk)
        if len(out) > limit:
            raise PayloadTooLarge(f"decompressed body exceeds {limit} bytes")
        # unconsumed_tail set means we hit max_length — more output pending than the ceiling allows
        if dec.unconsumed_tail:
            raise PayloadTooLarge(f"decompressed body exceeds {limit} bytes")
    out.extend(dec.flush())
    if len(out) > limit:
        raise PayloadTooLarge(f"decompressed body exceeds {limit} bytes")
    return bytes(out)


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def assert_public_endpoint(url: str | None, *, enabled: bool = True) -> None:
    """Raise EndpointBlocked if `url`'s host resolves to any non-public address (loopback, RFC-1918,
    link-local incl. 169.254.169.254 cloud metadata, reserved). No-op when `enabled` is False —
    single-tenant self-hosters legitimately point at internal storage and opt out via config.

    Best-effort against SSRF: it resolves the host and checks every returned address. It does not
    defend against DNS rebinding (the client re-resolves later); pair with network egress policy
    for a hard guarantee."""
    if not enabled or not url:
        return
    host = urlparse(url if "://" in url else f"//{url}", scheme="http").hostname
    if not host:
        raise EndpointBlocked(f"cannot parse host from {url!r}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise EndpointBlocked(f"cannot resolve {host!r}: {e}") from e
    for info in infos:
        ip = info[4][0]
        if not _is_public(ip):
            raise EndpointBlocked(f"{host!r} resolves to non-public address {ip}")
