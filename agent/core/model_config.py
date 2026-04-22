"""
多模型配置

支持不同任务使用不同模型，节省Token成本
"""

import os
from typing import Optional

from agno.models.siliconflow import Siliconflow


class ModelConfig:
    """多模型配置"""
    
    # 简单任务模型（低成本）- Base64解码、字段提取等
    SIMPLE_MODEL = "deepseek-ai/DeepSeek-V3"
    
    # 复杂推理模型（高成本）- 字段映射、意图理解等
    COMPLEX_MODEL = "deepseek-ai/DeepSeek-R1"
    
    # 主控模型（平衡）- 意图理解、任务协调
    MAIN_MODEL = "deepseek-ai/DeepSeek-V3.2"
    
    @staticmethod
    def get_api_key() -> str:
        """从环境变量获取API Key"""
        return os.getenv("SILICONFLOW_API_KEY", "")
    
    @staticmethod
    def get_simple_model() -> Siliconflow:
        """获取简单任务模型"""
        api_key = ModelConfig.get_api_key()
        if not api_key:
            raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
        
        return Siliconflow(
            id=ModelConfig.SIMPLE_MODEL,
            api_key=api_key
        )
    
    @staticmethod
    def get_complex_model() -> Siliconflow:
        """获取复杂推理模型"""
        api_key = ModelConfig.get_api_key()
        if not api_key:
            raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
        
        return Siliconflow(
            id=ModelConfig.COMPLEX_MODEL,
            api_key=api_key
        )
    
    @staticmethod
    def get_main_model() -> Siliconflow:
        """获取主控模型"""
        api_key = ModelConfig.get_api_key()
        if not api_key:
            raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
        
        return Siliconflow(
            id=ModelConfig.MAIN_MODEL,
            api_key=api_key
        )
