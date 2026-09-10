"""Best-effort, batched telemetry sender. Buffers events, flushes on a timer/threshold on a daemon
thread, POSTs one envelope per batch, and swallows every error — telemetry must never raise into or
slow down the worker. A no-op when disabled or unconfigured (no thread is started)."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.request
from typing import Any

from voiceobs.telemetry import config as tcfg
from voiceobs.telemetry.catalog import APP, SCHEMA_VERSION, allowed_dims
from voiceobs.telemetry.install import install_id

log = logging.getLogger(__name__)

PULSE_VERSION = "0.0.1"
_MAX_BATCH = 50
_MAX_BODY_BYTES = 256 * 1024
_POST_TIMEOUT_S = 5.0


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class TelemetryClient:
    def __init__(self, endpoint: str, *, flush_interval_s: float = 30.0) -> None:
        self._endpoint = endpoint
        self._flush_interval_s = flush_interval_s
        self._buf: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def emit(self, name: str, **dims: Any) -> None:
        allowed = allowed_dims(name)
        if allowed is None:  # unknown event — refuse rather than send free-form
            return
        clean = {k: v for k, v in dims.items() if k in allowed and v is not None}
        with self._lock:
            self._buf.append({"name": name, "ts": _now_iso(), "dims": clean})
            self._ensure_thread()

    def _ensure_thread(self) -> None:
        if self._thread is None:
            t = threading.Thread(target=self._loop, name="telemetry", daemon=True)
            self._thread = t
            t.start()

    def _loop(self) -> None:  # pragma: no cover — background timer
        while True:
            time.sleep(self._flush_interval_s)
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._buf:
                return
            events, self._buf = self._buf, []
        for i in range(0, len(events), _MAX_BATCH):
            self._post(events[i : i + _MAX_BATCH])

    def _envelope(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        body = {
            "app": APP,
            "schemaVersion": SCHEMA_VERSION,
            "installId": install_id(),
            "version": PULSE_VERSION,
            "events": events,
        }
        digest = hashlib.sha256(
            json.dumps(events, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        body["batchId"] = digest  # deterministic → server-side dedup
        return body

    def _post(self, events: list[dict[str, Any]]) -> None:
        try:
            payload = json.dumps(self._envelope(events)).encode()
            if len(payload) > _MAX_BODY_BYTES:
                log.debug("telemetry batch too large (%d bytes), dropped", len(payload))
                return
            req = urllib.request.Request(
                self._endpoint, data=payload, headers={"content-type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=_POST_TIMEOUT_S).close()
        except Exception as e:  # noqa: BLE001 — telemetry is best-effort, never raises
            log.debug("telemetry post failed: %s", e)


_client: TelemetryClient | None = None
_client_lock = threading.Lock()


def _get_client() -> TelemetryClient | None:
    """The process-wide client, or None when telemetry is off/unconfigured."""
    global _client
    if not tcfg.telemetry_enabled():
        return None
    ep = tcfg.endpoint()
    if not ep:
        return None
    with _client_lock:
        if _client is None or _client._endpoint != ep:
            _client = TelemetryClient(ep)
        return _client


def emit(name: str, **dims: Any) -> None:
    """Record an event. No-op when telemetry is disabled/unconfigured; never raises."""
    try:
        client = _get_client()
        if client is not None:
            client.emit(name, **dims)
    except Exception as e:  # noqa: BLE001 — telemetry must never raise into callers
        log.debug("telemetry emit failed: %s", e)


def flush() -> None:
    client = _get_client()
    if client is not None:
        client.flush()


def _reset_for_tests() -> None:
    global _client
    with _client_lock:
        _client = None
