"""提供商注册表与多模型配置（ADR-0007）。

每家提供商的全部接入参数以 ProviderSpec 单点声明；消费点（模型构造、
日志解析直连、设置界面）只经本模块公开查询接口取值，不感知具体提供商。
新增一家提供商 = 新增一条规格声明，消费点零改动。

密钥两套独立：聊天密钥按当前家环境变量解析（FALLBACK_API_KEY 兜底）；
嵌入向量密钥固定硅基流动，与聊天所选提供商无关（见 CONTEXT.md）。
"""

import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional

from agno.models.deepseek import DeepSeek
from agno.models.siliconflow import Siliconflow

# 自动加载.env文件
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("model_config")

# 思考模式禁用列表：这些模型默认思考会把结构化输出留在 reasoning_content，
# 导致 content 为空。全局模型级单点定义——思考是模型特性，与托管提供商无关。
THINKING_DISABLED_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})


@dataclass(frozen=True)
class ProviderSpec:
    """一家提供商的全部接入参数（提供商规格）。

    build_model 接收 (model_id, api_key, **options)，返回 agno 模型实例；
    options 仅在模型命中思考禁用列表时包含 extra_body。
    """

    name: str
    display_name: str
    api_key_env: str
    model_id_env: str
    default_model_id: str
    chat_completions_url: str
    models_list_url: str
    supports_json_response_format: bool
    default_models: tuple[str, ...] = ()
    build_model: Callable[..., object] = None


def _build_deepseek_model(model_id: str, api_key: str, **options):
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    return DeepSeek(
        id=model_id,
        api_key=api_key,
        base_url=base_url,
        timeout=90.0,
        max_retries=0,
        **options,
    )


def _build_siliconflow_model(model_id: str, api_key: str, **options):
    return Siliconflow(
        id=model_id,
        api_key=api_key,
        timeout=90.0,
        max_retries=0,
        **options,
    )


_PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek",
        display_name="DeepSeek",
        api_key_env="DEEPSEEK_API_KEY",
        model_id_env="DEEPSEEK_MODEL_ID",
        default_model_id="deepseek-chat",
        chat_completions_url="https://api.deepseek.com/v1/chat/completions",
        models_list_url="https://api.deepseek.com/v1/models",
        supports_json_response_format=True,
        default_models=(
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
        ),
        build_model=_build_deepseek_model,
    ),
    "siliconflow": ProviderSpec(
        name="siliconflow",
        display_name="SiliconFlow",
        api_key_env="SILICONFLOW_API_KEY",
        model_id_env="SILICONFLOW_MODEL",
        default_model_id="deepseek-ai/DeepSeek-V3.1-Terminus",
        chat_completions_url="https://api.siliconflow.cn/v1/chat/completions",
        models_list_url="https://api.siliconflow.cn/v1/models",
        supports_json_response_format=True,
        default_models=(
            "deepseek-ai/DeepSeek-V3.1-Terminus",
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-Coder-V2",
            "Qwen/Qwen2.5-7B-Instruct",
            "Qwen/Qwen2.5-14B-Instruct",
            "Qwen/Qwen2.5-72B-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct",
            "meta-llama/Llama-3.1-70B-Instruct",
            "meta-llama/Llama-3.1-8B-Instruct",
            "01-ai/Yi-1.5-34B-Chat",
            "THUDM/glm-4-9b-chat",
        ),
        build_model=_build_siliconflow_model,
    ),
}


def list_provider_names() -> list[str]:
    """返回全部已声明提供商名（设置界面下拉框数据源）。"""
    return list(_PROVIDER_SPECS)


def get_provider_spec(provider: str) -> ProviderSpec:
    """按名称查询提供商规格；未知名称抛出并列出已声明提供商。"""
    key = (provider or "").lower().strip()
    if key not in _PROVIDER_SPECS:
        raise ValueError(
            f"未知提供商: {provider}（已声明: {', '.join(_PROVIDER_SPECS)}）"
        )
    return _PROVIDER_SPECS[key]


def get_chat_completions_url(provider: Optional[str] = None) -> str:
    """返回直连 chat/completions 端点；DeepSeek 尊重其 BASE_URL 环境变量。"""
    spec = get_provider_spec(provider or ModelConfig.get_provider())
    if spec.name == "deepseek":
        base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        return f"{base}/v1/chat/completions"
    return spec.chat_completions_url


class ModelConfig:
    """多模型 / 多提供商配置（查注册表，环境变量优先、界面为会话级覆盖）。"""

    # ===== 运行时配置（会话级别） =====
    _runtime_provider: Optional[str] = None
    _runtime_api_key: Optional[str] = None
    _runtime_model: Optional[str] = None

    @classmethod
    def set_runtime_config(
        cls,
        provider: str = None,
        api_key: str = None,
        model: str = None
    ):
        """设置运行时配置（会话级覆盖）。"""
        if provider:
            cls._runtime_provider = provider.lower().strip()
        if api_key:
            cls._runtime_api_key = api_key
        if model:
            cls._runtime_model = model

    @classmethod
    def clear_runtime_config(cls):
        """清除运行时配置，回退到环境变量。"""
        cls._runtime_provider = None
        cls._runtime_api_key = None
        cls._runtime_model = None

    @staticmethod
    def get_provider() -> str:
        """获取当前供应商：运行时配置 > 环境变量（每次读取，不快照）。"""
        if ModelConfig._runtime_provider:
            return ModelConfig._runtime_provider
        return os.getenv("AGNO_MODEL_PROVIDER", "siliconflow").lower().strip()

    @staticmethod
    def get_api_key(provider: Optional[str] = None) -> str:
        """获取聊天 API Key：运行时配置 > 指定（或当前）家环境变量 > FALLBACK_API_KEY。

        provider 参数供设置保存等已知目标家的场景按表单所选家解析；
        缺省按当前供应商解析。
        """
        if ModelConfig._runtime_api_key:
            return ModelConfig._runtime_api_key
        spec = get_provider_spec(provider or ModelConfig.get_provider())
        primary = os.getenv(spec.api_key_env, "")
        if primary:
            return primary
        return os.getenv("FALLBACK_API_KEY", "")

    @staticmethod
    def _build_model(
        model_id: str,
        api_key: Optional[str] = None,
        provider: Optional[str] = None
    ):
        """按提供商规格动态构建模型实例；密钥缺失时抛出带具体变量名的错误。"""
        spec = get_provider_spec(provider or ModelConfig.get_provider())
        key = api_key or ModelConfig.get_api_key()
        if not key:
            raise ValueError(
                f"请设置环境变量 {spec.api_key_env}（或在设置界面填写 {spec.display_name} API Key）"
            )

        model_options = {}
        if model_id in THINKING_DISABLED_MODELS:
            model_options["extra_body"] = {"thinking": {"type": "disabled"}}

        logger.info(f"[MODEL] 使用 {spec.display_name}, model={model_id}")
        return spec.build_model(model_id=model_id, api_key=key, **model_options)

    @staticmethod
    def get_main_model():
        """获取主模型：运行时配置 > 当前家环境变量 > 规格默认值。"""
        return ModelConfig._build_model(ModelConfig.get_model_id())

    @staticmethod
    def get_model_id() -> str:
        """获取当前模型 ID 字符串：运行时配置 > 当前家环境变量 > 规格默认值。

        供需要模型 ID 字符串（非模型实例）的代码使用，
        如 Pipeline 直调 LLM、日志标签等。
        """
        if ModelConfig._runtime_model:
            return ModelConfig._runtime_model
        spec = get_provider_spec(ModelConfig.get_provider())
        return os.getenv(spec.model_id_env, "") or spec.default_model_id
