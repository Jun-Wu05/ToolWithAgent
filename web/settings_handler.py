"""Chainlit 设置全链路：控件构建、设置事件、模型列表与连接测试。

供应商接入参数一律查提供商注册表（ADR-0007），本模块不感知具体提供商；
原模型管理模块职责已并入本模块（设置界面是其唯一消费方）。
"""

import time
from typing import Dict, List

import chainlit as cl
import httpx
from chainlit.input_widget import Select, TextInput

from agent.core import model_config
from agent.core.model_config import ModelConfig
from agent.core.team import get_team_instance, reset_team_instance
from agent.shared.logger import get_logger

logger = get_logger("settings_handler")

RESET_OPTION = "--- 重置设置 ---"
MODEL_PLACEHOLDER = "请先配置 API Key 后获取模型列表"

# ============= 模型列表缓存 =============

_models_cache: Dict[str, tuple] = {}
"""模型列表缓存: {cache_key: (models_list, timestamp)}"""

CACHE_TTL = 10 * 24 * 60 * 60  # 10 天


def _provider_values() -> List[str]:
    """供应商下拉框 values：重置项第一位 + 注册表全部已声明提供商。"""
    return [RESET_OPTION] + model_config.list_provider_names()


def _provider_initial_index(provider: str) -> int:
    """按注册表位置计算供应商下拉框初始索引（重置项占第 0 位）。"""
    names = model_config.list_provider_names()
    if provider in names:
        return 1 + names.index(provider)
    return 0


def _curate_models(models: List[str], priority=(), per_vendor: int = 3, total: int = 60) -> List[str]:
    """超长模型列表按厂家精选封顶：优先保留规格默认模型，每家留代表、总量封顶。

    未超过总量上限时原样返回（去重保序），不改变短列表的展示。
    """
    models = list(dict.fromkeys(models))
    priority = [item for item in priority if item in models]
    if len(models) <= total:
        return models

    kept = list(dict.fromkeys(priority))
    per_vendor_count: Dict[str, int] = {}
    for item in kept:
        vendor = item.partition("/")[0]
        per_vendor_count[vendor] = per_vendor_count.get(vendor, 0) + 1

    for model_id in models:
        if len(kept) >= total:
            break
        if model_id in kept:
            continue
        vendor = model_id.partition("/")[0]
        if per_vendor_count.get(vendor, 0) >= per_vendor:
            continue
        kept.append(model_id)
        per_vendor_count[vendor] = per_vendor_count.get(vendor, 0) + 1
    return kept


def _grouped_model_items(models: List[str]) -> Dict[str, str]:
    """模型 ID 列表转分组展示 items：label=【厂家】模型，value=完整模型 ID。

    带厂家前缀的 ID（如 openrouter 的 vendor/model、硅基流动的 Qwen/...）
    按厂家排序聚合形成分组视觉；无前缀的模型保持原样。
    """
    grouped: Dict[str, List[str]] = {}
    for model_id in models:
        vendor, _, name = model_id.partition("/")
        grouped.setdefault(vendor if name else "", []).append(model_id)

    items: Dict[str, str] = {}
    for vendor in sorted(grouped, key=str.lower):
        for model_id in grouped[vendor]:
            short_name = model_id.partition("/")[2]
            label = f"【{vendor}】{short_name}" if vendor else model_id
            items[label] = model_id
    return items


def build_settings_widgets(provider=None, models=None, api_key="", selected_model=None):
    """构建设置界面三控件；供应商清单由注册表生成，模型列表按厂家分组渲染。"""
    if models:
        priority = ()
        if provider:
            try:
                priority = model_config.get_provider_spec(provider).default_models
            except ValueError:
                priority = ()
        items = _grouped_model_items(_curate_models(models, priority=priority))
        initial = None
        if items:
            values = list(items.values())
            initial = selected_model if selected_model in values else values[0]
        model_select = Select(
            id="model_name",
            label="模型名称",
            items=items,
            initial_value=initial,
        )
    else:
        model_select = Select(
            id="model_name",
            label="模型名称",
            values=[MODEL_PLACEHOLDER],
            initial_index=0,
        )
    return [
        Select(
            id="provider",
            label="供应商",
            values=_provider_values(),
            initial_index=_provider_initial_index(provider or ""),
        ),
        model_select,
        TextInput(
            id="api_key",
            label="API Key（可选，未填时使用环境变量）",
            placeholder="留空则使用 .env 中当前供应商的密钥",
            initial=api_key or "",
        ),
    ]


class ModelManager:
    """模型列表拉取与连接测试（按提供商注册表规格执行，静态默认表兜底）。"""

    @staticmethod
    async def get_models(
        provider: str,
        api_key: str = None,
        force_refresh: bool = False
    ) -> List[str]:
        """获取指定供应商的模型列表（带 10 天缓存；无密钥直接用静态默认表）。"""
        provider = (provider or "").lower().strip()
        if provider not in model_config.list_provider_names():
            logger.warning(f"[MODEL] 未知供应商: {provider}")
            return []
        spec = model_config.get_provider_spec(provider)
        if not (api_key or "").strip():
            return list(spec.default_models)
        return await ModelManager._get_cached_models(
            provider,
            api_key,
            force_refresh,
            lambda key: ModelManager._fetch_models(spec, key),
        )

    @staticmethod
    async def _get_cached_models(provider, api_key, force_refresh, fetch_fn) -> List[str]:
        """带缓存的模型列表获取（缓存键不含完整密钥）。"""
        cache_key = f"{provider}_{api_key[:8] if api_key else 'no_key'}"
        if not force_refresh:
            cached = _models_cache.get(cache_key)
            if cached:
                models, timestamp = cached
                if time.time() - timestamp < CACHE_TTL:
                    return models
        models = await fetch_fn(api_key)
        if models:
            _models_cache[cache_key] = (models, time.time())
        return models

    @staticmethod
    async def _fetch_models(spec, api_key: str) -> List[str]:
        """按规格端点拉取模型列表；失败回退静态默认表，不向调用方抛错。"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    spec.models_list_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()
                models = [m["id"] for m in data.get("data", []) if m.get("id")]
                logger.info(f"[API] {spec.display_name} 返回 {len(models)} 个模型")
                return models
        except Exception as e:
            logger.warning(
                f"[API] 获取 {spec.display_name} 模型列表失败: {e}，使用静态默认表"
            )
            return list(spec.default_models)

    @staticmethod
    def clear_cache() -> None:
        """清空所有模型列表缓存。"""
        _models_cache.clear()

    @staticmethod
    async def test_connection(provider: str, api_key: str = None, model: str = None) -> Dict:
        """测试指定供应商 API 连通性；无密钥按静态默认表返回成功。

        有密钥时两段验证（#123）：模型列表 GET + 1-token 最小对话 POST。
        对话探测暴露仅靠列表发现不了的问题——余额/配额不足（402）、
        模型不可用（404）等；成功文案同时注明可用模型数与下拉精选数，
        消除「可用 417 个」与下拉 60 个的口径落差。
        """
        provider = (provider or "").lower().strip()
        if provider not in model_config.list_provider_names():
            return {
                "success": False,
                "message": f"❌ 未知供应商: {provider}",
                "models_count": 0,
                "models": [],
            }
        spec = model_config.get_provider_spec(provider)
        if not (api_key or "").strip():
            models = list(spec.default_models)
            return {
                "success": True,
                "message": (
                    "✅ 使用静态模型列表（密钥来自环境变量）："
                    f"可用 {len(models)} 个，下拉精选 {len(_curate_models(models))} 个"
                ),
                "models_count": len(models),
                "models": models,
            }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    spec.models_list_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                if response.status_code == 401:
                    return {
                        "success": False,
                        "message": "❌ API Key 无效",
                        "models_count": 0,
                        "models": [],
                    }
                if response.status_code != 200:
                    return {
                        "success": False,
                        "message": f"❌ 请求失败 (HTTP {response.status_code})",
                        "models_count": 0,
                        "models": [],
                    }
                data = response.json()
                models = [m["id"] for m in data.get("data", []) if m.get("id")]

                # 第二段：1-token 最小对话请求，验证聊天链路与余额/配额（#123）
                probe_model = (model or "").strip()
                if not probe_model and spec.default_models:
                    probe_model = spec.default_models[0]
                if not probe_model and models:
                    probe_model = models[0]
                if not probe_model:
                    return {
                        "success": True,
                        "message": "✅ 连接成功（无可用模型名，未验证对话链路）",
                        "models_count": len(models),
                        "models": models,
                    }
                chat_url = model_config.get_chat_completions_url(spec.name)
                chat_response = await client.post(
                    chat_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": probe_model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                    timeout=20.0,
                )
                if chat_response.status_code == 402:
                    return {
                        "success": False,
                        "message": (
                            "❌ 余额/配额不足（HTTP 402）：模型列表可访问，"
                            "但对话请求被拒，请充值后重试"
                        ),
                        "models_count": 0,
                        "models": [],
                    }
                if chat_response.status_code == 404:
                    return {
                        "success": False,
                        "message": f"❌ 模型不可用（HTTP 404）: {probe_model}",
                        "models_count": 0,
                        "models": [],
                    }
                if chat_response.status_code != 200:
                    return {
                        "success": False,
                        "message": (
                            f"❌ 对话请求失败 (HTTP {chat_response.status_code})，"
                            "模型列表可访问但聊天链路异常"
                        ),
                        "models_count": 0,
                        "models": [],
                    }
                return {
                    "success": True,
                    "message": (
                        f"✅ 连接成功（对话链路已验证，模型 {probe_model}）："
                        f"可用模型 {len(models)} 个，"
                        f"下拉精选 {len(_curate_models(models))} 个"
                    ),
                    "models_count": len(models),
                    "models": models,
                }
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "❌ 请求超时，请检查网络连接",
                "models_count": 0,
                "models": [],
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "message": "❌ 网络连接失败，请检查代理设置",
                "models_count": 0,
                "models": [],
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ 未知错误: {str(e)}",
                "models_count": 0,
                "models": [],
            }


async def on_settings_update(settings: dict):
    """
    当用户修改设置时触发。

    功能：
    1. 获取用户配置的供应商、模型、API Key
    2. 检测供应商是否切换
    3. 如果切换供应商，清空模型列表并提示
    4. 按「最终解析结果」校验密钥（.env 已配则放行，不要求界面重填）
    5. 测试 API 连通性；成功后应用配置，失败则不应用
    6. 重新初始化 Team 实例并更新设置界面模型列表
    """
    user_session = cl.user_session.get("user_session")

    # 获取新的配置（使用 or 确保返回字符串，避免 None.strip() 报错）
    provider = (settings.get("provider") or "").strip()
    model = (settings.get("model_name") or "").strip()
    if model == MODEL_PLACEHOLDER:
        # Chainlit Select 必须有一个可提交值；首次设置时不能让展示占位文本
        # 穿过表单接缝成为真实模型 ID，空值会由连接探针选择规格默认模型。
        model = ""
    api_key = (settings.get("api_key") or "").strip()

    # 获取旧配置
    old_provider = user_session.current_provider

    # 使用界面的 API Key，或按表单所选供应商解析环境变量密钥
    test_key = api_key if api_key else ModelConfig.get_api_key(provider or None)

    # 检测供应商是否切换
    provider_changed = old_provider and provider and old_provider != provider

    # 检测是否点击了重置选项
    if provider == RESET_OPTION:
        # 重置配置
        user_session.current_provider = None
        user_session.model_name = None
        user_session.api_key = None

        # 清除运行时配置
        ModelConfig.clear_runtime_config()

        # 清除 Team 缓存
        reset_team_instance()
        user_session.team = None

        logger.info("[SETTINGS] 设置已重置")

        await cl.ChatSettings(build_settings_widgets()).send()

        await cl.Message(
            content="""🔄 **设置已重置为默认值**

💡 请重新配置模型：
1. 选择供应商
2. 输入 API Key（留空则使用 .env 环境变量密钥）
3. 点击保存自动测试连接

⚙️ **当前默认配置：**
- 供应商：环境变量 AGNO_MODEL_PROVIDER
- API Key：环境变量
- Team：未初始化（下次消息或配置后自动初始化）"""
        ).send()
        return

    # 如果供应商切换了，先清空模型列表等待用户再次保存
    if provider_changed:
        await cl.ChatSettings(
            build_settings_widgets(provider=provider, api_key=api_key)
        ).send()

        await cl.Message(
            content=f"""🔄 **供应商已切换为 {provider}**

💡 请配置 API Key 后点击保存，自动测试连接并获取模型列表。"""
        ).send()
        return  # 切换供应商后，等待用户再次点击保存

    # 密钥最终解析结果为空时拦截（各供应商口径一致）
    if not test_key:
        spec = model_config.get_provider_spec(provider)
        await cl.Message(
            content=f"""❌ **{spec.display_name} 需要配置 API Key**

💡 请在设置界面输入 API Key，或设置环境变量 {spec.api_key_env}。"""
        ).send()
        return

    # 发送测试中消息
    loading_msg = cl.Message(content="🔌 **正在测试连接...**")
    await loading_msg.send()

    # 测试连接（携带用户所选模型做对话探测；#123）
    result = await ModelManager.test_connection(provider, test_key, model=model)

    # 移除加载消息
    await loading_msg.remove()

    if result["success"]:
        # 测试成功，应用配置
        user_session.current_provider = provider if provider else None
        user_session.model_name = model if model else None
        user_session.api_key = api_key if api_key else None

        # 应用运行时配置
        ModelConfig.set_runtime_config(
            provider=user_session.current_provider,
            api_key=user_session.api_key,
            model=user_session.model_name
        )

        # 清除单例缓存并重新初始化 Team
        reset_team_instance()
        user_session.team = get_team_instance()

        logger.info("[SETTINGS] Team 已重新初始化")

        # 获取最新的模型列表并重发设置界面（按厂家分组渲染）
        models = result.get("models", [])
        await cl.ChatSettings(
            build_settings_widgets(
                provider=provider, models=models, api_key=api_key, selected_model=model
            )
        ).send()

        await cl.Message(
            content=f"""✅ **配置更新成功！**

📊 **测试结果：**
- {result['message']}
- 可用模型：{result['models_count']} 个

🤖 **当前配置：**
- 供应商：{provider or '使用默认'}
- 模型：{model or '使用默认'}
- API Key：{'✅ 界面配置' if api_key else '✅ 环境变量'}

💡 模型列表已更新，请从侧边栏选择模型。"""
        ).send()

    else:
        # 测试失败，不应用配置
        await cl.Message(
            content=f"""❌ **配置测试失败**

📊 **测试结果：**
- {result['message']}

💡 请检查：
1. API Key 是否正确
2. 网络连接是否正常
3. 是否需要配置代理

💡 配置未应用，请修正后重试。"""
        ).send()
