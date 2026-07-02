"""
模型管理器 - 支持多供应商（DeepSeek + SiliconFlow）

功能：
1. 从 API 动态获取模型列表（带10天缓存）
2. 测试 API 连通性
3. 统一的模型获取接口
"""

import httpx
import time
from typing import List, Dict, Tuple, Optional
from agent.shared.logger import get_logger

logger = get_logger("model_manager")

# ============= 缓存配置 =============

_models_cache: Dict[str, Tuple[List[str], float]] = {}
"""模型列表缓存: {cache_key: (models_list, timestamp)}"""

CACHE_TTL = 10 * 24 * 60 * 60  # 10 天 = 864000 秒

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
        api_key: str = None,
        force_refresh: bool = False
    ) -> List[str]:
        """
        获取指定供应商的模型列表（带10天缓存）
        
        Args:
            provider: 供应商名称（"deepseek" | "siliconflow"）
            api_key: API 密钥（DeepSeek 需要，SiliconFlow 暂不需要）
            force_refresh: 是否强制刷新缓存
        
        Returns:
            模型 ID 列表
        """
        provider = provider.lower().strip()
        
        if provider == "deepseek":
            if not api_key:
                logger.warning("[MODEL] DeepSeek 需要 API Key")
                return DEEPSEEK_DEFAULT_MODELS.copy()
            return await ModelManager._get_cached_models(
                "deepseek", 
                api_key, 
                force_refresh,
                lambda k: ModelManager._fetch_deepseek_models(k)
            )
        elif provider == "siliconflow":
            # SiliconFlow 也使用缓存
            return await ModelManager._get_cached_models(
                "siliconflow",
                api_key or "",
                force_refresh,
                lambda k: ModelManager._fetch_siliconflow_models(k)
            )
        else:
            logger.warning(f"[MODEL] 未知供应商: {provider}")
            return []
    
    @staticmethod
    async def _get_cached_models(
        provider: str,
        api_key: str,
        force_refresh: bool,
        fetch_fn
    ) -> List[str]:
        """
        获取模型列表（带缓存逻辑）
        
        Args:
            provider: 供应商名称
            api_key: API 密钥（用于生成缓存键）
            force_refresh: 是否强制刷新
            fetch_fn: 获取模型列表的异步函数
        
        Returns:
            模型 ID 列表
        """
        # 生成缓存键（避免缓存完整 API Key）
        cache_key = f"{provider}_{api_key[:8] if api_key else 'no_key'}"
        
        # 检查缓存
        if not force_refresh:
            cached_data = _models_cache.get(cache_key)
            if cached_data:
                models, timestamp = cached_data
                cache_age_days = (time.time() - timestamp) / (24 * 60 * 60)
                
                if time.time() - timestamp < CACHE_TTL:
                    logger.info(f"[CACHE] 使用缓存模型列表: {provider}, 缓存年龄: {cache_age_days:.1f} 天")
                    return models
                else:
                    logger.info(f"[CACHE] 缓存已过期: {provider} (缓存 {cache_age_days:.1f} 天), 重新获取")
        
        # 缓存失效或强制刷新，重新获取
        logger.info(f"[API] 获取模型列表: {provider}")
        models = await fetch_fn(api_key)
        
        # 更新缓存
        if models:
            _models_cache[cache_key] = (models, time.time())
            logger.info(f"[CACHE] 已缓存 {len(models)} 个模型: {provider}, 有效期: 10 天")
        
        return models
    
    @staticmethod
    async def _fetch_deepseek_models(api_key: str) -> List[str]:
        """从 DeepSeek API 获取模型列表（私有方法）"""
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
                logger.info(f"[API] DeepSeek API 返回 {len(models)} 个模型")
                return models
        except httpx.TimeoutException:
            logger.error("[API] DeepSeek 请求超时，使用默认列表")
            return DEEPSEEK_DEFAULT_MODELS.copy()
        except httpx.ConnectError:
            logger.error("[API] DeepSeek 网络连接失败，使用默认列表")
            return DEEPSEEK_DEFAULT_MODELS.copy()
        except Exception as e:
            logger.error(f"[API] 获取 DeepSeek 模型列表失败: {e}，使用默认列表")
            return DEEPSEEK_DEFAULT_MODELS.copy()
    
    @staticmethod
    async def _fetch_siliconflow_models(api_key: str = None) -> List[str]:
        """从 SiliconFlow API 获取模型列表（私有方法）"""
        
        # 没有 API Key，直接使用静态列表
        if not api_key or not api_key.strip():
            logger.info("[API] SiliconFlow 未提供 API Key，使用静态列表")
            all_models = []
            for models in SILICONFLOW_MODELS.values():
                all_models.extend(models)
            return all_models
        
        # 有 API Key，尝试从 API 获取
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.siliconflow.cn/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    params={
                        "type": "text",
                        "sub_type": "chat"
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                models = [model.get("id", "") for model in data.get("data", [])]
                models = [m for m in models if m]  # 过滤空值
                logger.info(f"[API] SiliconFlow API 返回 {len(models)} 个模型")
                return models
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.warning("[API] SiliconFlow API Key 无效，使用静态列表")
            else:
                logger.warning(f"[API] SiliconFlow API 请求失败 ({e.response.status_code})，使用静态列表")
        except httpx.TimeoutException:
            logger.warning("[API] SiliconFlow 请求超时，使用静态列表")
        except httpx.ConnectError:
            logger.warning("[API] SiliconFlow 网络连接失败，使用静态列表")
        except Exception as e:
            logger.warning(f"[API] SiliconFlow API 请求失败: {e}，使用静态列表")
        
        # API 失败，使用静态列表
        all_models = []
        for models in SILICONFLOW_MODELS.values():
            all_models.extend(models)
        logger.info(f"[API] SiliconFlow 使用静态列表: {len(all_models)} 个模型")
        return all_models
    
    @staticmethod
    def clear_cache() -> None:
        """清空所有缓存"""
        global _models_cache
        count = len(_models_cache)
        _models_cache.clear()
        logger.info(f"[CACHE] 已清空 {count} 个缓存条目")
    
    @staticmethod
    def clear_cache_by_provider(provider: str) -> None:
        """清空指定供应商的缓存"""
        global _models_cache
        provider = provider.lower().strip()
        count = 0
        for key in list(_models_cache.keys()):
            if key.startswith(f"{provider}_"):
                del _models_cache[key]
                count += 1
        logger.info(f"[CACHE] 已清空 {provider} 的 {count} 个缓存条目")
    
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
            return await ModelManager._test_siliconflow_connection(api_key)
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
    
    @staticmethod
    async def _test_siliconflow_connection(api_key: str = None) -> Dict:
        """测试 SiliconFlow API 连通性"""
        # 如果没有 API Key，直接返回成功（SiliconFlow 可以使用静态列表）
        if not api_key or not api_key.strip():
            models = await ModelManager.get_models("siliconflow")
            return {
                "success": True,
                "message": "✅ 使用静态模型列表（无需 API Key）",
                "models_count": len(models),
                "models": models
            }
        
        # 有 API Key，测试 API 连通性
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.siliconflow.cn/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    params={"type": "text", "sub_type": "chat"},
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models = [model.get("id", "") for model in data.get("data", [])]
                    models = [m for m in models if m]
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
