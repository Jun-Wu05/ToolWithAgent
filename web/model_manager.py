"""
模型管理器 - 支持多供应商（DeepSeek + SiliconFlow）

功能：
1. 从 DeepSeek API 动态获取模型列表
2. 支持 SiliconFlow 静态模型列表（预留）
3. 测试 API 连通性
4. 统一的模型获取接口
"""

import httpx
from typing import List, Dict
from agent.shared.logger import get_logger

logger = get_logger("model_manager")

# 默认模型列表（API 失败时回退）
DEEPSEEK_DEFAULT_MODELS = [
    "deepseek-chat",        # 通用对话模型
    "deepseek-reasoner",    # 推理增强模型
    "deepseek-v4-pro",      # V4 Pro 版本
    "deepseek-v4-flash",    # V4 快速版本
]

# SiliconFlow 静态模型列表（预留）
SILICONFLOW_MODELS = {
    "DeepSeek 系列": [
        "deepseek-ai/DeepSeek-V3.1-Terminus",
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-Coder-V2",
    ],
    "Qwen 系列": [
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen/Qwen2.5-72B-Instruct",
        "Qwen/Qwen2.5-14B-Instruct",
    ],
    "Llama 系列": [
        "meta-llama/Llama-3.3-70B-Instruct",
        "meta-llama/Llama-3.1-70B-Instruct",
        "meta-llama/Llama-3.1-8B-Instruct",
    ],
    "其他": [
        "01-ai/Yi-1.5-34B-Chat",
        "THUDM/glm-4-9b-chat",
    ],
}


class ModelManager:
    """模型管理器 - 支持多供应商"""
    
    @staticmethod
    async def get_models(
        provider: str,
        api_key: str = None
    ) -> List[str]:
        """
        获取指定供应商的模型列表
        
        Args:
            provider: 供应商名称（"deepseek" | "siliconflow"）
            api_key: API 密钥（DeepSeek 需要，SiliconFlow 暂不需要）
        
        Returns:
            模型 ID 列表
        """
        provider = provider.lower().strip()
        
        if provider == "deepseek":
            return await ModelManager.get_deepseek_models(api_key)
        elif provider == "siliconflow":
            # SiliconFlow 使用静态列表
            all_models = []
            for models in SILICONFLOW_MODELS.values():
                all_models.extend(models)
            return all_models
        else:
            logger.warning(f"[MODEL] 未知供应商: {provider}")
            return []
    
    @staticmethod
    async def get_deepseek_models(api_key: str) -> List[str]:
        """从 DeepSeek API 获取模型列表"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                models = [model["id"] for model in data.get("data", [])]
                logger.info(f"[MODEL] DeepSeek API 返回 {len(models)} 个模型")
                return models
        except Exception as e:
            logger.error(f"[MODEL] 获取 DeepSeek 模型列表失败: {e}，使用默认列表")
            return DEEPSEEK_DEFAULT_MODELS.copy()
    
    @staticmethod
    async def test_connection(
        provider: str,
        api_key: str = None
    ) -> Dict:
        """
        测试 API 连通性
        
        Args:
            provider: 供应商名称
            api_key: API 密钥
        
        Returns:
            {
                "success": bool,
                "message": str,
                "models_count": int,
                "models": List[str]
            }
        """
        provider = provider.lower().strip()
        
        if provider == "deepseek":
            if not api_key:
                return {
                    "success": False,
                    "message": "❌ DeepSeek 需要 API Key",
                    "models_count": 0,
                    "models": []
                }
            return await ModelManager._test_deepseek_connection(api_key)
        elif provider == "siliconflow":
            # SiliconFlow 暂不支持连通性测试
            return {
                "success": True,
                "message": "✅ SiliconFlow 预留（暂不支持连通性测试）",
                "models_count": len(await ModelManager.get_models("siliconflow")),
                "models": await ModelManager.get_models("siliconflow")
            }
        else:
            return {
                "success": False,
                "message": f"❌ 未知供应商: {provider}",
                "models_count": 0,
                "models": []
            }
    
    @staticmethod
    async def _test_deepseek_connection(api_key: str) -> Dict:
        """测试 DeepSeek API 连通性"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models = [model["id"] for model in data.get("data", [])]
                    return {
                        "success": True,
                        "message": "✅ 连接成功",
                        "models_count": len(models),
                        "models": models
                    }
                elif response.status_code == 401:
                    return {
                        "success": False,
                        "message": "❌ API Key 无效",
                        "models_count": 0,
                        "models": []
                    }
                else:
                    return {
                        "success": False,
                        "message": f"❌ 请求失败 (HTTP {response.status_code})",
                        "models_count": 0,
                        "models": []
                    }
                    
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "❌ 请求超时，请检查网络连接",
                "models_count": 0,
                "models": []
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": "❌ 网络连接失败，请检查代理设置",
                "models_count": 0,
                "models": []
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ 未知错误: {str(e)}",
                "models_count": 0,
                "models": []
            }