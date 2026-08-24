"""设置界面与 Team 懒初始化的提供商注册表契约（Issue #119 / PRD #116）。

供应商下拉框由注册表生成；模型列表/连接测试按规格端点执行、静态表兜底；
设置保存按「最终解析结果」校验密钥；消息到达时 Team 懒初始化（.env 优先）。
"""

import asyncio
from types import SimpleNamespace

import agent.core.model_config as model_config
import web.settings_handler as settings_handler
from agent.core.model_config import ModelConfig


def _clean_env(monkeypatch):
    """清空运行时配置与提供商/密钥变量，回到可控基线。"""
    ModelConfig.clear_runtime_config()
    for var in (
        "AGNO_MODEL_PROVIDER",
        "DEEPSEEK_API_KEY",
        "SILICONFLOW_API_KEY",
        "FALLBACK_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------- 下拉框来源 ----------

def test设置界面供应商下拉框由注册表生成():
    """values 来自注册表：已声明提供商全部出现，重置项保持第一位。"""
    widgets = settings_handler.build_settings_widgets()
    provider_select = widgets[0]
    assert provider_select.id == "provider"
    assert provider_select.values[0] == "--- 重置设置 ---"
    for name in model_config.list_provider_names():
        assert name in provider_select.values


# ---------- 模型列表 / 连接测试 ----------

class _FakeAsyncClient:
    """记录 GET 请求的 httpx.AsyncClient 替身。"""

    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None, params=None, timeout=None):
        type(self).calls.append({"url": url, "headers": headers, "params": params})
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"id": "m-alpha"}, {"id": "m-beta"}]},
        )


def test模型列表无密钥时静态默认表兜底():
    """无密钥直接返回规格静态默认表，不发网络请求。"""
    models = asyncio.run(settings_handler.ModelManager.get_models("siliconflow", None))
    assert "deepseek-ai/DeepSeek-V3.1-Terminus" in models
    assert "Qwen/Qwen2.5-7B-Instruct" in models


def test模型列表按规格端点拉取(monkeypatch):
    """有密钥时按规格声明的列表端点与鉴权头拉取。"""
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(settings_handler.httpx, "AsyncClient", _FakeAsyncClient)

    models = asyncio.run(
        settings_handler.ModelManager.get_models("siliconflow", "sf-key")
    )

    assert models == ["m-alpha", "m-beta"]
    spec = model_config.get_provider_spec("siliconflow")
    assert _FakeAsyncClient.calls[0]["url"] == spec.models_list_url
    assert _FakeAsyncClient.calls[0]["headers"]["Authorization"] == "Bearer sf-key"


def test模型列表请求失败时回退静态默认表(monkeypatch):
    """拉取异常时回退规格静态默认表，不向用户抛错。"""

    class _BrokenClient(_FakeAsyncClient):
        async def get(self, url, **kwargs):
            raise settings_handler.httpx.ConnectError("network down")

    monkeypatch.setattr(settings_handler.httpx, "AsyncClient", _BrokenClient)

    models = asyncio.run(
        settings_handler.ModelManager.get_models("deepseek", "ds-key")
    )

    assert "deepseek-chat" in models


def test连接测试无密钥返回静态表成功():
    """无密钥时连接测试按静态表返回成功（.env 优先：密钥可来自环境变量）。"""
    result = asyncio.run(
        settings_handler.ModelManager.test_connection("siliconflow", None)
    )
    assert result["success"] is True
    assert result["models"]


# ---------- 模型列表按厂家分组展示 ----------

def test模型列表按厂家分组展示():
    """带厂家前缀的模型 ID 分组渲染：label 为【厂家】模型，提交值仍是完整 ID。"""
    widgets = settings_handler.build_settings_widgets(
        provider="openrouter",
        models=[
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4",
            "deepseek/deepseek-chat",
            "openai/gpt-4o",
        ],
    )
    model_select = widgets[1]
    items = model_select.items
    assert items["【openai】gpt-4o-mini"] == "openai/gpt-4o-mini"
    assert items["【deepseek】deepseek-chat"] == "deepseek/deepseek-chat"
    assert items["【anthropic】claude-sonnet-4"] == "anthropic/claude-sonnet-4"
    # 同厂家模型相邻（分组视觉）
    labels = list(items)
    assert abs(labels.index("【openai】gpt-4o-mini") - labels.index("【openai】gpt-4o")) == 1


def test无斜杠模型保持原样展示():
    """无厂家前缀的模型 ID（如智谱）不加分组头，label 与提交值一致。"""
    widgets = settings_handler.build_settings_widgets(
        provider="zhipu", models=["glm-4.6", "glm-4-flash"]
    )
    items = widgets[1].items
    assert items["glm-4.6"] == "glm-4.6"
    assert items["glm-4-flash"] == "glm-4-flash"


def test超长模型列表按厂家精选封顶():
    """超过总量上限时按厂家精选：每家保留代表模型，优先保留规格默认表。"""
    models = []
    for vendor_index in range(10):
        vendor = f"vendor{vendor_index}"
        for model_index in range(10):
            models.append(f"{vendor}/model-{model_index}")
    priority = ("vendor0/model-9", "vendor9/model-0")

    curated = settings_handler._curate_models(models, priority=priority)

    assert len(curated) <= 60
    by_vendor = {}
    for model_id in curated:
        by_vendor.setdefault(model_id.split("/")[0], []).append(model_id)
    assert all(len(entries) <= 3 for entries in by_vendor.values())
    # 规格默认模型在精选中不被裁掉
    assert "vendor0/model-9" in curated and "vendor9/model-0" in curated


def test未超上限的列表不做精选():
    """短列表原样返回，不触发封顶逻辑。"""
    models = ["deepseek-chat", "deepseek-reasoner"]
    assert settings_handler._curate_models(models) == models


# ---------- 设置保存的密钥校验口径 ----------

def _install_chainlit_fakes(monkeypatch, session):
    """替换 settings_handler 的 chainlit 表面，记录发出的消息与控件。"""
    sent = []

    class _Message:
        def __init__(self, *, content=""):
            self.content = content

        async def send(self):
            sent.append(self.content)

        async def remove(self):
            pass

    class _Settings:
        def __init__(self, widgets):
            self.widgets = widgets

        async def send(self):
            sent.append("<WIDGETS>")

    fake_cl = SimpleNamespace(
        Message=_Message,
        ChatSettings=_Settings,
        user_session=SimpleNamespace(get=lambda key: session),
    )
    monkeypatch.setattr(settings_handler, "cl", fake_cl)
    return sent


def test设置保存按最终解析结果校验并放行环境变量密钥(monkeypatch):
    """界面密钥留空但环境变量已有当前家密钥时不被要求重填。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    session = SimpleNamespace(
        current_provider=None, model_name=None, api_key=None, team=None
    )
    sent = _install_chainlit_fakes(monkeypatch, session)
    tested = []

    async def _fake_test(provider, key):
        tested.append(key)
        return {
            "success": True,
            "message": "ok",
            "models_count": 2,
            "models": ["deepseek-chat", "deepseek-reasoner"],
        }

    monkeypatch.setattr(
        settings_handler.ModelManager, "test_connection", staticmethod(_fake_test)
    )
    from agent.core.team import reset_team_instance

    try:
        asyncio.run(
            settings_handler.on_settings_update(
                {"provider": "deepseek", "model_name": "", "api_key": ""}
            )
        )

        assert tested == ["env-key"]
        assert ModelConfig.get_provider() == "deepseek"
        assert session.team is not None
        assert any("✅" in item for item in sent)
    finally:
        ModelConfig.clear_runtime_config()
        reset_team_instance()


def test设置保存密钥解析为空时拦截并提示变量名(monkeypatch):
    """当前家与环境变量都解析不出密钥时拦截，提示含具体变量名。"""
    _clean_env(monkeypatch)
    session = SimpleNamespace(
        current_provider=None, model_name=None, api_key=None, team=None
    )
    sent = _install_chainlit_fakes(monkeypatch, session)
    called = []

    async def _fake_test(provider, key):
        called.append(provider)
        return {"success": True, "message": "ok", "models_count": 0, "models": []}

    monkeypatch.setattr(
        settings_handler.ModelManager, "test_connection", staticmethod(_fake_test)
    )

    asyncio.run(
        settings_handler.on_settings_update(
            {"provider": "deepseek", "model_name": "", "api_key": ""}
        )
    )

    assert called == []
    assert any("DEEPSEEK_API_KEY" in item for item in sent)


# ---------- Team 懒初始化（.env 优先） ----------

def _install_router_fakes(monkeypatch, session, handled):
    import web.message_router as router

    class _Handlers:
        async def handle_user_message(self, user_session, team, user_text):
            handled.append((user_session, team, user_text))

    monkeypatch.setattr(router, "get_user_message_handlers", lambda: _Handlers())

    sent = []

    class _Message:
        def __init__(self, *, content=""):
            self.content = content

        async def send(self):
            sent.append(self.content)

    monkeypatch.setattr(router.cl, "Message", _Message)
    monkeypatch.setattr(
        router.cl, "user_session", SimpleNamespace(get=lambda key: session)
    )
    return router, sent


def test环境变量密钥就绪时消息到达自动创建Team(monkeypatch):
    """Team 未初始化且配置可解析时自动懒创建，不再拒绝消息。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    from agent.core.team import reset_team_instance

    reset_team_instance()
    session = SimpleNamespace(team=None)
    handled = []
    router, sent = _install_router_fakes(monkeypatch, session, handled)

    try:
        message = SimpleNamespace(elements=[], content="日志类型提取")
        asyncio.run(router.on_message(message))

        assert handled and handled[0][1] is not None
        assert session.team is not None
    finally:
        reset_team_instance()
        ModelConfig.clear_runtime_config()


def test密钥缺失时消息到达提示应设置变量名(monkeypatch):
    """配置解析不出密钥时返回包含变量名的明确提示，取代死路文案。"""
    _clean_env(monkeypatch)
    from agent.core.team import reset_team_instance

    reset_team_instance()
    session = SimpleNamespace(team=None)
    handled = []
    router, sent = _install_router_fakes(monkeypatch, session, handled)

    try:
        message = SimpleNamespace(elements=[], content="日志类型提取")
        asyncio.run(router.on_message(message))

        assert handled == []
        assert any("SILICONFLOW_API_KEY" in item for item in sent)
    finally:
        reset_team_instance()
