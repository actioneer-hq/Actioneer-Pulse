"""Auth-provider registry — same shape as frameworks' registry. Providers register by
import side-effect (see auth/__init__.py)."""

from __future__ import annotations

from voiceobs.auth.protocol import AuthProvider

_REGISTRY: dict[str, AuthProvider] = {}


def register_provider(provider: AuthProvider) -> None:
    _REGISTRY[provider.name] = provider


def provider_for(name: str) -> AuthProvider | None:
    return _REGISTRY.get(name)


def providers() -> dict[str, AuthProvider]:
    return dict(_REGISTRY)
