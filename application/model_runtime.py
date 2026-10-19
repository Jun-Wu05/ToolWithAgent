"""Model configuration and Team lifecycle exposed to delivery adapters."""

from __future__ import annotations

from typing import Any

from agent.core.model_config import (
    EffectiveModelConfig,
    ModelConfig,
    model_runtime_scope,
    resolve_effective_config,
)
from agent.core.team import create_data_mapping_team
from application.session_state import SessionState


def resolve_api_key(provider: str | None) -> str | None:
    """Resolve the effective key for a provider using runtime/environment policy."""
    return ModelConfig.get_api_key(provider or None)


def resolve_session_config(session: SessionState) -> EffectiveModelConfig:
    """从会话覆盖解析该会话下一次请求的有效配置快照。"""
    return resolve_effective_config(
        provider=session.current_provider,
        model=session.model_name,
        api_key=session.api_key,
    )


def ensure_team(session: SessionState) -> Any:
    """Return the session Team, lazily creating it inside the session model scope."""
    if session.team is None:
        with model_runtime_scope(resolve_session_config(session)):
            session.team = create_data_mapping_team()
    return session.team


def apply_model_settings(
    session: SessionState,
    provider: str | None,
    model: str | None,
    api_key: str | None,
) -> Any:
    """原子应用模型设置：先用候选配置成功构建候选 Team，再同时提交（#192）。"""
    candidate = resolve_effective_config(
        provider=provider or None,
        model=model or None,
        api_key=api_key or None,
    )
    with model_runtime_scope(candidate):
        candidate_team = create_data_mapping_team()
    session.current_provider = provider or None
    session.model_name = model or None
    session.api_key = api_key or None
    session.team = candidate_team
    return session.team


def reset_model_settings(session: SessionState) -> None:
    """Clear only this session's model overrides and cached Team."""
    session.current_provider = None
    session.model_name = None
    session.api_key = None
    session.team = None
