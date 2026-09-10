"""Typed emit helpers — the only sanctioned way to send events. Keeps call sites from passing
free-form dimensions and centralizes the bucketing that keeps counts non-identifying."""

from __future__ import annotations

from voiceobs.telemetry.client import PULSE_VERSION, emit


def _bucket(n: int) -> str:
    """Coarse count bucket so we never send exact tenant volumes."""
    for hi, label in ((0, "0"), (1, "1"), (10, "2-10"), (100, "11-100"), (1000, "101-1k")):
        if n <= hi:
            return label
    return "1k+"


def heartbeat() -> None:
    emit("deploy.heartbeat", version=PULSE_VERSION)


def feature_used(
    adapter: str,
    *,
    audio: bool = False,
    backfill: bool = False,
    chat: bool = False,
    judge: bool = False,
    calls: int = 1,
) -> None:
    emit(
        "feature.used",
        adapter=adapter,
        audio=audio,
        backfill=backfill,
        chat=chat,
        judge=judge,
        calls_bucket=_bucket(calls),
    )


def error_occurred(reason: str, where: str) -> None:
    """`reason`/`where` are short codes (e.g. 'unsupported_schema', 'analysis') — never messages."""
    emit("error.occurred", reason=reason, where=where)


def agent_configured(
    use_case: str | None = None, framework: str | None = None, language: str | None = None
) -> None:
    """A voice agent onboarded via the wizard. `use_case` is a short, non-identifying market
    descriptor; framework/language are the producer stack. All optional — absent dims are dropped."""
    emit("agent.configured", use_case=use_case, framework=framework, language=language)
