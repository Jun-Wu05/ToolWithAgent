"""直连链路提供商注册表契约（Issue #118 / PRD #116）。

直连请求的端点、密钥与 JSON 能力来自当前提供商规格；运行时切换后随切换刷新，
不再使用懒加载缓存或 import 时类属性快照；DeepSeek 尊重 BASE_URL 环境变量。
"""

import dataclasses
import json

import agent.core.model_config as model_config
import agent.tools.pipeline.llm_client as llm_client
from agent.core.model_config import model_runtime_scope, resolve_effective_config


class _FakeResponse:
    """记录请求并返回最小合法 chat/completions 响应。"""

    def __init__(self) -> None:
        self.calls = []

    def add(self, url, payload, headers):
        self.calls.append({"url": url, "payload": payload, "headers": headers})

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


def _install_httpx_mock(monkeypatch):
    """把 httpx.post 替换为记录请求的假件，返回响应记录器。"""
    response = _FakeResponse()

    def _fake_post(url, json=None, headers=None, timeout=None):
        response.add(url, json, headers)
        return response

    monkeypatch.setattr(llm_client.httpx, "post", _fake_post)
    return response


def _clean_env(monkeypatch):
    """清空全部密钥/提供商变量（回到硅基流动默认），避免真实 .env 干扰。"""
    for var in (
        "AGNO_MODEL_PROVIDER",
        "DEEPSEEK_API_KEY",
        "SILICONFLOW_API_KEY",
        "FALLBACK_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test直连请求按当前提供商规格发送端点与密钥(monkeypatch):
    """端点、密钥来自规格与当前家环境变量，不再走硬编码分支。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    response = _install_httpx_mock(monkeypatch)

    llm_client._call_llm_direct("测试提示", model_id="Qwen/Qwen2.5-7B-Instruct")

    assert response.calls[0]["url"] == "https://api.siliconflow.cn/v1/chat/completions"
    assert response.calls[0]["headers"]["Authorization"] == "Bearer sf-key"
    assert response.calls[0]["payload"]["response_format"] == {"type": "json_object"}


def test运行时切换提供商后端点密钥能力随切换刷新(monkeypatch):
    """切换后新请求走新家端点（缓存缺陷回归锁），不再打旧家。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    response = _install_httpx_mock(monkeypatch)

    llm_client._call_llm_direct("第一句", model_id="Qwen/Qwen2.5-7B-Instruct")
    with model_runtime_scope(
        resolve_effective_config(provider="deepseek", api_key="ds-key")
    ):
        llm_client._call_llm_direct("第二句", model_id="deepseek-chat")

    assert response.calls[0]["url"] == "https://api.siliconflow.cn/v1/chat/completions"
    assert response.calls[1]["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert response.calls[1]["headers"]["Authorization"] == "Bearer ds-key"


def testDeepSeek直连端点尊重BASE_URL环境变量(monkeypatch):
    """自定义 BASE_URL 生效于直连端点（原缺陷：只影响 agno 构造）。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek-proxy.example.com")
    response = _install_httpx_mock(monkeypatch)

    with model_runtime_scope(
        resolve_effective_config(provider="deepseek", api_key="ds-key")
    ):
        llm_client._call_llm_direct("提示", model_id="deepseek-chat")

    assert (
        response.calls[0]["url"]
        == "https://deepseek-proxy.example.com/v1/chat/completions"
    )


def testJSON能力声明为不支持时请求不含response_format(monkeypatch):
    """能力来自规格声明：不支持的家靠提示词约束，不传 response_format。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    response = _install_httpx_mock(monkeypatch)
    real_spec = model_config.get_provider_spec("siliconflow")
    capped = dataclasses.replace(real_spec, supports_json_response_format=False)
    monkeypatch.setattr(model_config, "get_provider_spec", lambda name: capped)

    llm_client._call_llm_direct("测试提示", model_id="Qwen/Qwen2.5-7B-Instruct")

    assert "response_format" not in response.calls[0]["payload"]


def test思考禁用模型直连请求携带禁用参数(monkeypatch):
    """命中全局思考禁用列表的模型，直连请求携带 thinking disabled。"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    response = _install_httpx_mock(monkeypatch)

    llm_client._call_llm_direct("测试提示", model_id="deepseek-v4-flash")

    assert response.calls[0]["payload"]["thinking"] == {"type": "disabled"}
