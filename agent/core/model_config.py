"""
多模型配置

支持不同任务使用不同模型，节省Token成本
支持从.env文件自动读取API Key
支持双模型 Fallback（主模型 + 备用模型）
支持多 Provider：SiliconFlow / DeepSeek 原生 API（通过 AGNO_MODEL_PROVIDER 切换）
"""

import os
import logging
from typing import Optional, Union

from agno.models.siliconflow import Siliconflow
from agno.models.deepseek import DeepSeek

# 自动加载.env文件
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("model_config")


class ModelConfig:
    """多模型 / 多 Provider 配置"""

    # ===== Provider 切换 =====
    # AGNO_MODEL_PROVIDER: "siliconflow"（默认） | "deepseek"
    MODEL_PROVIDER = os.getenv("AGNO_MODEL_PROVIDER", "siliconflow").lower().strip()

    # ===== 模型 ID =====
    # SiliconFlow 上使用 deepseek-ai/DeepSeek-V3.1-Terminus
    # DeepSeek 原生使用 deepseek-chat
    if MODEL_PROVIDER == "deepseek":
        MAIN_MODEL = os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
    else:
        MAIN_MODEL = os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.1-Terminus")

    # 备用模型（主模型不可用时的 fallback）
    FALLBACK_MODEL = os.getenv(
        "FALLBACK_MODEL_ID",
        "Qwen/Qwen2.5-7B-Instruct"
    )

    # 是否启用 fallback
    FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "true").lower() == "true"

    @staticmethod
    def get_api_key() -> str:
        """从环境变量获取当前 Provider 对应的 API Key"""
        if ModelConfig.MODEL_PROVIDER == "deepseek":
            primary = os.getenv("DEEPSEEK_API_KEY", "")
            if primary:
                return primary
        primary = os.getenv("SILICONFLOW_API_KEY", "")
        if primary:
            return primary
        return os.getenv("FALLBACK_API_KEY", "")

    @staticmethod
    def _build_model(
        model_id: str,
        api_key: Optional[str] = None
    ) -> Union[Siliconflow, DeepSeek]:
        """
        根据 AGNO_MODEL_PROVIDER 动态构建模型实例。

        - siliconflow → Siliconflow(id=model_id, api_key=key)
        - deepseek    → DeepSeek(id=model_id, api_key=key, base_url=...)
        """
        key = api_key or ModelConfig.get_api_key()

        if ModelConfig.MODEL_PROVIDER == "deepseek":
            if not key:
                raise ValueError("请设置环境变量 DEEPSEEK_API_KEY")
            base_url = os.getenv(
                "DEEPSEEK_BASE_URL",
                "https://api.deepseek.com"
            )
            logger.info(f"[MODEL] 使用 DeepSeek 原生 API, model={model_id}")
            return DeepSeek(id=model_id, api_key=key, base_url=base_url)

        # 默认 siliconflow
        if not key:
            raise ValueError("请设置环境变量 SILICONFLOW_API_KEY 或 DEEPSEEK_API_KEY")
        logger.info(f"[MODEL] 使用 SiliconFlow API, model={model_id}")
        return Siliconflow(id=model_id, api_key=key)

    @staticmethod
    def get_main_model() -> Union[Siliconflow, DeepSeek]:
        """获取主模型"""
        return ModelConfig._build_model(ModelConfig.MAIN_MODEL)

    @staticmethod
    def get_fallback_model() -> Union[Siliconflow, DeepSeek]:
        """获取备用模型"""
        return ModelConfig._build_model(ModelConfig.FALLBACK_MODEL)

    @staticmethod
    def get_model_with_fallback() -> dict:
        """
        获取带降级配置的模型字典

        Returns:
            {
                "primary": Siliconflow|DeepSeek (主模型),
                "fallback": Siliconflow|DeepSeek (备用模型),
                "fallback_enabled": bool,
            }
        """
        if not ModelConfig.FALLBACK_ENABLED:
            return {
                "primary": ModelConfig.get_main_model(),
                "fallback": None,
                "fallback_enabled": False,
            }

        main_model = ModelConfig.get_main_model()
        fallback_model = None
        try:
            fallback_model = ModelConfig.get_fallback_model()
        except ValueError:
            pass

        return {
            "primary": main_model,
            "fallback": fallback_model,
            "fallback_enabled": fallback_model is not None,
        }
