"""会话级模型运行时隔离（#192）：请求快照、并发隔离与生命周期。

全部使用假件与离线构造，不访问真实模型或外部网络。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent.core.model_config import (
    ModelConfig,
    model_runtime_scope,
    resolve_effective_config,
)
from application import model_runtime


def _session(**overrides):
    """构造带模型覆盖字段的会话假件。"""
    fields = dict(current_provider=None, model_name=None, api_key=None, team=None)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test请求快照内读取一致且回落环境默认(monkeypatch):
    """作用域内 get_* 读取同一快照；退出后回落环境默认。"""
    monkeypatch.delenv("AGNO_MODEL_PROVIDER", raising=False)
    config = resolve_effective_config(
        provider="deepseek", model="deepseek-chat", api_key="key-a"
    )
    assert (config.provider, config.model_id, config.api_key) == (
        "deepseek",
        "deepseek-chat",
        "key-a",
    )
    with model_runtime_scope(config):
        assert ModelConfig.get_provider() == "deepseek"
        assert ModelConfig.get_model_id() == "deepseek-chat"
        assert ModelConfig.get_api_key() == "key-a"
    assert ModelConfig.get_provider() == "siliconflow"


def test无会话覆盖时按环境与注册表解析(monkeypatch):
    """无覆盖走 ADR-0007 优先级：AGNO_MODEL_PROVIDER > 家环境变量 > 注册表默认。"""
    monkeypatch.setenv("AGNO_MODEL_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.delenv("DEEPSEEK_MODEL_ID", raising=False)

    config = resolve_effective_config()

    assert config.provider == "deepseek"
    assert config.api_key == "env-key"
    assert config.model_id == "deepseek-chat"


def test会话间模型配置互不串扰():
    """会话 B 应用设置不改变会话 A 的请求配置（last-writer-wins 回归）。"""
    session_a = _session()
    session_b = _session()
    model_runtime.apply_model_settings(session_a, "deepseek", "deepseek-chat", "key-a")
    model_runtime.apply_model_settings(session_b, "zhipu", "glm-4.6", "key-b")

    with model_runtime_scope(model_runtime.resolve_session_config(session_a)):
        assert ModelConfig.get_provider() == "deepseek"
        assert ModelConfig.get_api_key() == "key-a"
        assert ModelConfig.get_model_id() == "deepseek-chat"
    with model_runtime_scope(model_runtime.resolve_session_config(session_b)):
        assert ModelConfig.get_provider() == "zhipu"
        assert ModelConfig.get_api_key() == "key-b"
        assert ModelConfig.get_model_id() == "glm-4.6"


def test请求进行中修改设置不影响本请求():
    """进行中请求保持启动时快照，下一请求使用新配置。"""
    session = _session()
    model_runtime.apply_model_settings(session, "deepseek", "deepseek-chat", "key-a")
    with model_runtime_scope(model_runtime.resolve_session_config(session)):
        model_runtime.apply_model_settings(session, "zhipu", "glm-4.6", "key-b")
        assert ModelConfig.get_provider() == "deepseek"
        assert ModelConfig.get_api_key() == "key-a"
    with model_runtime_scope(model_runtime.resolve_session_config(session)):
        assert ModelConfig.get_provider() == "zhipu"


def test重置仅清理目标会话的覆盖与Team():
    """重置会话 A 不影响会话 B 的配置与已缓存 Team。"""
    session_a = _session()
    session_b = _session()
    team_a = model_runtime.apply_model_settings(
        session_a, "deepseek", "deepseek-chat", "key-a"
    )
    team_b = model_runtime.apply_model_settings(session_b, "zhipu", "glm-4.6", "key-b")

    model_runtime.reset_model_settings(session_a)

    assert (session_a.current_provider, session_a.model_name, session_a.api_key) == (
        None,
        None,
        None,
    )
    assert session_a.team is None
    assert session_b.team is team_b
    assert session_b.current_provider == "zhipu"


def test嵌套作用域与异常后正确恢复():
    """嵌套 scope 退出恢复外层；scope 内异常不泄漏配置。"""
    outer = resolve_effective_config(
        provider="deepseek", model="deepseek-chat", api_key="key-a"
    )
    inner = resolve_effective_config(provider="zhipu", model="glm-4.6", api_key="key-b")
    with model_runtime_scope(outer):
        with model_runtime_scope(inner):
            assert ModelConfig.get_provider() == "zhipu"
        assert ModelConfig.get_provider() == "deepseek"
        with pytest.raises(RuntimeError):
            with model_runtime_scope(inner):
                raise RuntimeError("boom")
        assert ModelConfig.get_provider() == "deepseek"


def test候选Team构建失败时原子保留原状态(monkeypatch):
    """候选配置构建 Team 失败时，会话原配置与 Team 保持不变。"""
    session = _session()
    old_team = model_runtime.apply_model_settings(
        session, "deepseek", "deepseek-chat", "key-a"
    )

    def _boom():
        raise ValueError("构建失败")

    monkeypatch.setattr(model_runtime, "create_data_mapping_team", _boom)
    with pytest.raises(ValueError):
        model_runtime.apply_model_settings(session, "zhipu", "glm-4.6", "key-b")

    assert session.current_provider == "deepseek"
    assert session.model_name == "deepseek-chat"
    assert session.api_key == "key-a"
    assert session.team is old_team


def test并发任务各自读取本会话配置():
    """两个会话的请求并发交错时各自读取本会话配置。"""
    session_a = _session(
        current_provider="deepseek", model_name="deepseek-chat", api_key="key-a"
    )
    session_b = _session(current_provider="zhipu", model_name="glm-4.6", api_key="key-b")

    async def scenario():
        entered_a = asyncio.Event()
        entered_b = asyncio.Event()
        release = asyncio.Event()
        reads = {}

        async def run(session, name, entered):
            with model_runtime_scope(model_runtime.resolve_session_config(session)):
                entered.set()
                await release.wait()
                reads[name] = (ModelConfig.get_provider(), ModelConfig.get_api_key())

        task_a = asyncio.create_task(run(session_a, "a", entered_a))
        task_b = asyncio.create_task(run(session_b, "b", entered_b))
        await asyncio.gather(entered_a.wait(), entered_b.wait())
        release.set()
        await asyncio.gather(task_a, task_b)
        return reads

    reads = asyncio.run(scenario())
    assert reads["a"] == ("deepseek", "key-a")
    assert reads["b"] == ("zhipu", "key-b")


def testTeam缓存于会话且创建于会话作用域内(monkeypatch):
    """Team 只缓存于 SessionState；创建时读取该会话作用域配置，无进程级单例。"""
    built_providers = []
    teams = iter([object(), object()])

    def _fake_create():
        built_providers.append(ModelConfig.get_provider())
        return next(teams)

    monkeypatch.setattr(model_runtime, "create_data_mapping_team", _fake_create)

    session = _session(current_provider="zhipu", model_name="glm-4.6", api_key="key-z")
    team_first = model_runtime.ensure_team(session)
    assert model_runtime.ensure_team(session) is team_first
    assert built_providers == ["zhipu"]

    other = _session()
    assert model_runtime.ensure_team(other) is not team_first


def test自然语言请求入口绑定会话作用域(monkeypatch):
    """run_user_request 全链在同一会话作用域内（Planner 读到会话配置）。"""
    from application import request_runtime
    from application.progress import NullProgressSink
    from application.session_state import SessionState
    from contracts.planner_models import PlanDecision

    session = SessionState()
    session.current_provider = "zhipu"
    session.model_name = "glm-4.6"
    session.api_key = "key-z"

    seen = []

    class _ScopedPlanner:
        async def plan(self, **kwargs):
            seen.append(
                (
                    ModelConfig.get_provider(),
                    ModelConfig.get_model_id(),
                    ModelConfig.get_api_key(),
                )
            )
            return PlanDecision.model_validate(
                {
                    "decision": "clarification",
                    "plan_id": "plan-scope",
                    "reason_code": "scope_probe",
                    "question": "请确认",
                }
            )

    monkeypatch.setattr(request_runtime, "PlannerService", _ScopedPlanner)

    asyncio.run(
        request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="你好",
            progress_sink=NullProgressSink(),
            progress_plan_id="scope-check",
        )
    )

    assert seen == [("zhipu", "glm-4.6", "key-z")]
