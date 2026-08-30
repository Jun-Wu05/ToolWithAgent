"""Model configuration and Team lifecycle exposed to delivery adapters."""

from __future__ import annotations

from typing import Any

from agent.core.model_config import ModelConfig
from agent.core.team import get_team_instance, reset_team_instance


def resolve_api_key(provider: str | None) -> str | None:
    """Resolve the effective key for a provider using runtime/environment policy."""
    return ModelConfig.get_api_key(provider or None)


def ensure_team(session: Any) -> Any:
    """Return the session Team, lazily creating it from effective configuration."""
    if session.team is None:
        session.team = get_team_instance()
    return session.team


def apply_model_settings(
    session: Any,
    provider: str | None,
    model: str | None,
    api_key: str | None,
) -> Any:
    """Apply a selected model configuration and rebuild the session Team."""
    session.current_provider = provider or None
    session.model_name = model or None
    session.api_key = api_key or None
    ModelConfig.set_runtime_config(
        provider=session.current_provider,
        api_key=session.api_key,
        model=session.model_name,
    )
    reset_team_instance()
    session.team = get_team_instance()
    return session.team


def reset_model_settings(session: Any) -> None:
    """Clear runtime model configuration and the cached Team."""
    session.current_provider = None
    session.model_name = None
    session.api_key = None
    ModelConfig.clear_runtime_config()
    reset_team_instance()
    session.team = None
