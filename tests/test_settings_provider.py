"""设置界面与 Team 懒初始化的提供商注册表契约（Issue #119 / PRD #116）。

供应商下拉框由注册表生成；模型列表/连接测试按规格端点执行、静态表兜底；
设置保存按「最终解析结果」校验密钥；消息到达时 Team 懒初始化（.env 优先）。
"""

import asyncio
from types import SimpleNamespace

import agent.core.model_config as model_config
import web.settings_handler as settings_handler


def _clean_env(monkeypatch):
    """清空提供商/密钥环境变量，回到可控基线。"""
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


# ---------- 连接测试的对话探测（#123） ----------


class _ProbeAsyncClient:
    """GET 模型列表 + POST 对话探测的 httpx.AsyncClient 替身。

    chat_status 控制对话探测响应码；post_calls 记录探测请求供断言。
    """

    post_calls = []
    chat_status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None, params=None, timeout=None):
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"id": "m-alpha"}, {"id": "m-beta"}]},
        )

    async def post(self, url, headers=None, json=None, timeout=None):
        type(self).post_calls.append({"url": url, "headers": headers, "json": json})
        return SimpleNamespace(status_code=type(self).chat_status)


def test连接测试发对话探测并注明精选数(monkeypatch):
    """列表成功后追加 1-token 对话探测；成功文案含可用数与精选数（#123）。"""
    _ProbeAsyncClient.post_calls = []
    _ProbeAsyncClient.chat_status = 200
    monkeypatch.setattr(settings_handler.httpx, "AsyncClient", _ProbeAsyncClient)

    result = asyncio.run(
        settings_handler.ModelManager.test_connection(
            "siliconflow", "sf-key", model="m-alpha"
        )
    )

    assert result["success"] is True
    assert "对话链路已验证" in result["message"]
    assert "可用模型 2 个" in result["message"]
    assert "下拉精选" in result["message"]
    # 探测请求：规格聊天端点 + 鉴权头 + 所选模型 + max_tokens=1
    spec = model_config.get_provider_spec("siliconflow")
    assert len(_ProbeAsyncClient.post_calls) == 1
    probe = _ProbeAsyncClient.post_calls[0]
    assert probe["url"] == model_config.get_chat_completions_url(spec.name)
    assert probe["headers"]["Authorization"] == "Bearer sf-key"
    assert probe["json"]["model"] == "m-alpha"
    assert probe["json"]["max_tokens"] == 1


def test连接测试未选模型时用规格默认表首个探测(monkeypatch):
    """用户未选模型时用规格默认表的第一个模型做对话探测。"""
    _ProbeAsyncClient.post_calls = []
    _ProbeAsyncClient.chat_status = 200
    monkeypatch.setattr(settings_handler.httpx, "AsyncClient", _ProbeAsyncClient)

    result = asyncio.run(
        settings_handler.ModelManager.test_connection("siliconflow", "sf-key", model="")
    )

    assert result["success"] is True
    spec = model_config.get_provider_spec("siliconflow")
    assert _ProbeAsyncClient.post_calls[0]["json"]["model"] == spec.default_models[0]


def test连接测试余额不足返回四十二(monkeypatch):
    """对话探测 402 → 明确的余额/配额文案（模型列表可访问的假阳性被揭穿）。"""
    _ProbeAsyncClient.post_calls = []
    _ProbeAsyncClient.chat_status = 402
    monkeypatch.setattr(settings_handler.httpx, "AsyncClient", _ProbeAsyncClient)

    result = asyncio.run(
        settings_handler.ModelManager.test_connection("openrouter", "or-key")
    )

    assert result["success"] is False
    assert "余额/配额不足" in result["message"]
    assert "402" in result["message"]


def test连接测试模型不可用返回四零四(monkeypatch):
    """对话探测 404 → 模型不可用文案并列出模型名。"""
    _ProbeAsyncClient.chat_status = 404
    monkeypatch.setattr(settings_handler.httpx, "AsyncClient", _ProbeAsyncClient)

    result = asyncio.run(
        settings_handler.ModelManager.test_connection("siliconflow", "sf-key", model="m-alpha")
    )

    assert result["success"] is False
    assert "模型不可用" in result["message"]
    assert "m-alpha" in result["message"]


def test连接测试无密钥静态分支文案含精选数():
    """无密钥静态表成功文案同步注明可用数与精选数。"""
    result = asyncio.run(
        settings_handler.ModelManager.test_connection("siliconflow", None)
    )
    assert result["success"] is True
    assert "下拉精选" in result["message"]


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

    async def _fake_test(provider, key, model=None):
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

    asyncio.run(
        settings_handler.on_settings_update(
            {"provider": "deepseek", "model_name": "", "api_key": ""}
        )
    )

    assert tested == ["env-key"]
    assert session.current_provider == "deepseek"
    assert session.team is not None
    assert any("✅" in item for item in sent)


def test首次设置不把模型占位文本提交给连接探针(monkeypatch):
    """首次设置应把展示占位值规范化为空模型，让探针选择规格默认模型。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    placeholder = settings_handler.build_settings_widgets()[1].values[0]
    session = SimpleNamespace(
        current_provider=None, model_name=None, api_key=None, team=None
    )
    _install_chainlit_fakes(monkeypatch, session)
    tested_models = []
    team = object()

    async def _fake_test(provider, key, model=None):
        tested_models.append(model)
        return {
            "success": True,
            "message": "ok",
            "models_count": 2,
            "models": ["deepseek-chat", "deepseek-reasoner"],
        }

    monkeypatch.setattr(
        settings_handler.ModelManager, "test_connection", staticmethod(_fake_test)
    )
    def _apply_model_settings(user_session, provider, model, api_key):
        user_session.current_provider = provider or None
        user_session.model_name = model or None
        user_session.api_key = api_key or None
        user_session.team = team
        return team

    monkeypatch.setattr(settings_handler, "apply_model_settings", _apply_model_settings)

    asyncio.run(
        settings_handler.on_settings_update(
            {
                "provider": "deepseek",
                "model_name": placeholder,
                "api_key": "",
            }
        )
    )

    assert tested_models == [""]
    assert session.model_name is None
    assert session.team is team


def test设置保存密钥解析为空时拦截并提示变量名(monkeypatch):
    """当前家与环境变量都解析不出密钥时拦截，提示含具体变量名。"""
    _clean_env(monkeypatch)
    session = SimpleNamespace(
        current_provider=None, model_name=None, api_key=None, team=None
    )
    sent = _install_chainlit_fakes(monkeypatch, session)
    called = []

    async def _fake_test(provider, key, model=None):
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
    session = SimpleNamespace(team=None)
    handled = []
    router, sent = _install_router_fakes(monkeypatch, session, handled)

    message = SimpleNamespace(elements=[], content="日志类型提取")
    asyncio.run(router.on_message(message))

    assert handled and handled[0][1] is not None
    assert session.team is not None


def test密钥缺失时消息到达提示应设置变量名(monkeypatch):
    """配置解析不出密钥时返回包含变量名的明确提示，取代死路文案。"""
    _clean_env(monkeypatch)
    session = SimpleNamespace(team=None)
    handled = []
    router, sent = _install_router_fakes(monkeypatch, session, handled)

    message = SimpleNamespace(elements=[], content="日志类型提取")
    asyncio.run(router.on_message(message))

    assert handled == []
    assert any("SILICONFLOW_API_KEY" in item for item in sent)
