"""提供商注册表契约（Issue #117 / PRD #116 / ADR-0007）。

注册表是提供商接入参数的唯一事实来源：单点声明每家的构造方式、密钥环境变量、
直连端点与 JSON 能力；消费点经公开查询接口取值（ADR-0007）。
"""

import pytest

from agent.core.model_config import (
    ModelConfig,
    model_runtime_scope,
    resolve_effective_config,
)


def test注册表声明现有两家提供商规格():
    """DeepSeek 与硅基流动以 ProviderSpec 声明，字段可经公开接口查询。"""
    from agent.core.model_config import get_provider_spec, list_provider_names

    names = list_provider_names()
    assert "deepseek" in names
    assert "siliconflow" in names

    deepseek = get_provider_spec("deepseek")
    assert deepseek.api_key_env == "DEEPSEEK_API_KEY"
    assert deepseek.model_id_env == "DEEPSEEK_MODEL_ID"
    assert deepseek.default_model_id == "deepseek-chat"
    assert deepseek.chat_completions_url == "https://api.deepseek.com/v1/chat/completions"
    assert deepseek.supports_json_response_format is True

    siliconflow = get_provider_spec("siliconflow")
    assert siliconflow.api_key_env == "SILICONFLOW_API_KEY"
    assert siliconflow.model_id_env == "SILICONFLOW_MODEL"
    assert siliconflow.default_model_id == "deepseek-ai/DeepSeek-V3.1-Terminus"
    assert siliconflow.chat_completions_url == "https://api.siliconflow.cn/v1/chat/completions"
    assert siliconflow.supports_json_response_format is True


def test按规格构造DeepSeek与Siliconflow模型():
    """构造出正确的 agno 模型类与参数，行为与迁移前一致。"""
    from agno.models.deepseek import DeepSeek
    from agno.models.siliconflow import Siliconflow

    deepseek_model = ModelConfig._build_model(
        "deepseek-chat", api_key="test-key", provider="deepseek"
    )
    assert isinstance(deepseek_model, DeepSeek)
    assert deepseek_model.base_url == "https://api.deepseek.com"

    siliconflow_model = ModelConfig._build_model(
        "Qwen/Qwen2.5-7B-Instruct", api_key="test-key", provider="siliconflow"
    )
    assert isinstance(siliconflow_model, Siliconflow)


def test密钥解析请求快照优先于环境变量(monkeypatch):
    """密钥链：请求快照 > 当前家环境变量 > FALLBACK_API_KEY。"""
    monkeypatch.setenv("AGNO_MODEL_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")

    assert ModelConfig.get_api_key() == "env-key"
    with model_runtime_scope(
        resolve_effective_config(
            provider="deepseek", model="deepseek-chat", api_key="snapshot-key"
        )
    ):
        assert ModelConfig.get_api_key() == "snapshot-key"
    assert ModelConfig.get_api_key() == "env-key"


def test密钥缺失时报错包含具体环境变量名(monkeypatch):
    """各家缺失口径一致：构造时抛出带具体变量名的错误。"""
    for var in ("DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY", "FALLBACK_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValueError) as excinfo:
        ModelConfig._build_model("deepseek-chat", provider="deepseek")
    assert "DEEPSEEK_API_KEY" in str(excinfo.value)


def test思考禁用列表为全局单点定义():
    """直连链路与模型构造共享同一份模型级思考禁用列表，不再重复定义。"""
    import agent.tools.pipeline.llm_client as llm_client
    from agent.core.model_config import THINKING_DISABLED_MODELS

    assert "deepseek-v4-flash" in THINKING_DISABLED_MODELS
    assert llm_client._THINKING_DISABLED_MODELS is THINKING_DISABLED_MODELS


def test团队构造在密钥缺失时统一抛出带变量名的错误(monkeypatch):
    """Team 构造不再区分提供商告警或抛错，统一由模型构造层报具体变量名。"""
    from agent.core import team as team_module

    for var in ("DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY", "FALLBACK_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    with model_runtime_scope(resolve_effective_config(provider="siliconflow")):
        with pytest.raises(ValueError) as excinfo:
            team_module.create_data_mapping_team()
        assert "SILICONFLOW_API_KEY" in str(excinfo.value)


def test注册表新增智谱OpenAI与OpenRouter三家规格():
    """三家新提供商以纯声明接入：字段齐备、JSON 能力声明为支持。"""
    from agent.core.model_config import get_provider_spec, list_provider_names

    for name in ("zhipu", "openai", "openrouter"):
        assert name in list_provider_names()

    zhipu = get_provider_spec("zhipu")
    assert zhipu.api_key_env == "ZHIPU_API_KEY"
    assert zhipu.chat_completions_url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert zhipu.supports_json_response_format is True
    assert zhipu.default_models  # 只收录支持结构化输出的模型

    openai = get_provider_spec("openai")
    assert openai.api_key_env == "OPENAI_API_KEY"
    assert openai.chat_completions_url == "https://api.openai.com/v1/chat/completions"
    assert openai.supports_json_response_format is True

    openrouter = get_provider_spec("openrouter")
    assert openrouter.api_key_env == "OPENROUTER_API_KEY"
    assert openrouter.chat_completions_url == "https://openrouter.ai/api/v1/chat/completions"
    assert openrouter.supports_json_response_format is True


def test三家按规格构造正确的agno模型类():
    """智谱构造 OpenAILike（OpenAI 兼容端点），OpenAI/OpenRouter 用各自原生类。"""
    from agno.models.openai import OpenAIChat, OpenAILike
    from agno.models.openrouter import OpenRouter

    zhipu_model = ModelConfig._build_model(
        "glm-4.6", api_key="k", provider="zhipu"
    )
    assert isinstance(zhipu_model, OpenAILike)
    assert zhipu_model.base_url == "https://open.bigmodel.cn/api/paas/v4"

    openai_model = ModelConfig._build_model(
        "gpt-4o", api_key="k", provider="openai"
    )
    assert isinstance(openai_model, OpenAIChat)

    openrouter_model = ModelConfig._build_model(
        "openai/gpt-4o-mini", api_key="k", provider="openrouter"
    )
    assert isinstance(openrouter_model, OpenRouter)


def test三家密钥缺失时报错含各自变量名(monkeypatch):
    """各家缺失口径一致：报错文案含本家环境变量名。"""
    for var in (
        "ZHIPU_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "FALLBACK_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    for provider, env_name in (
        ("zhipu", "ZHIPU_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
    ):
        with pytest.raises(ValueError) as excinfo:
            ModelConfig._build_model("any-model", provider=provider)
        assert env_name in str(excinfo.value)


def test三家自动出现在设置界面供应商下拉框():
    """注册表声明即出现在下拉框——「新增一家只加一条声明」的端到端验证。"""
    from web.settings_handler import build_settings_widgets

    values = build_settings_widgets()[0].values
    for name in ("zhipu", "openai", "openrouter"):
        assert name in values
