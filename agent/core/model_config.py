"""
多模型配置

支持不同任务使用不同模型，节省Token成本
支持从.env文件自动读取API Key
支持双模型 Fallback（主模型 + 备用模型）
"""

import os
from typing import Optional

from agno.models.siliconflow import Siliconflow

# 自动加载.env文件
from dotenv import load_dotenv
load_dotenv()


class ModelConfig:
    """多模型配置"""

    # 主模型（平衡），优先从环境变量 SILICONFLOW_MODEL 读取
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
        """从环境变量获取 API Key（支持主/备 Key）"""
        # 优先使用主 Key，为空则尝试备用 Key
        primary = os.getenv("SILICONFLOW_API_KEY", "")
        if primary:
            return primary
        return os.getenv("FALLBACK_API_KEY", "")

    @staticmethod
    def _build_model(model_id: str, api_key: Optional[str] = None) -> Siliconflow:
        """构建 Siliconflow 模型实例"""
        key = api_key or ModelConfig.get_api_key()
        if not key:
            raise ValueError("请设置环境变量 SILICONFLOW_API_KEY 或 FALLBACK_API_KEY")
        return Siliconflow(id=model_id, api_key=key)

    @staticmethod
    def get_main_model() -> Siliconflow:
        """获取主模型"""
        return ModelConfig._build_model(ModelConfig.MAIN_MODEL)

    @staticmethod
    def get_fallback_model() -> Siliconflow:
        """获取备用模型"""
        return ModelConfig._build_model(ModelConfig.FALLBACK_MODEL)

    @staticmethod
    def get_model_with_fallback() -> dict:
        """
        获取带降级配置的模型字典

        Returns:
            {
                "primary": Siliconflow (主模型),
                "fallback": Siliconflow (备用模型),
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
