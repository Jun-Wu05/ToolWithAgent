"""提供商注册表契约（Issue #117 / PRD #116 / ADR-0007）。

注册表是提供商接入参数的唯一事实来源：单点声明每家的构造方式、密钥环境变量、
直连端点与 JSON 能力；消费点经公开查询接口取值（ADR-0007）。
"""

import pytest

from agent.core.model_config import ModelConfig


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


def test密钥解析运行时优先于环境变量(monkeypatch):
    """密钥链：运行时会话配置 > 当前家环境变量 > FALLBACK_API_KEY。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    try:
        ModelConfig.set_runtime_config(api_key="runtime-key")
        assert ModelConfig.get_api_key() == "runtime-key"
        ModelConfig.clear_runtime_config()
        assert ModelConfig.get_api_key() == "env-key"
    finally:
        ModelConfig.clear_runtime_config()


def test密钥缺失时报错包含具体环境变量名(monkeypatch):
    """各家缺失口径一致：构造时抛出带具体变量名的错误。"""
    for var in ("DEEPSEEK_API_KEY", "SILICONFLOW_API_KEY", "FALLBACK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    ModelConfig.clear_runtime_config()

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
    ModelConfig.clear_runtime_config()
    ModelConfig.set_runtime_config(provider="siliconflow")
    try:
        with pytest.raises(ValueError) as excinfo:
            team_module.create_data_mapping_team()
        assert "SILICONFLOW_API_KEY" in str(excinfo.value)
    finally:
        ModelConfig.clear_runtime_config()
