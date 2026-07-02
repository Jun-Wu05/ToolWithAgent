"""
Chainlit 设置更新处理器 - 从 chainlit_app.py 提取

本模块处理 @cl.on_settings_update 事件。
"""

import chainlit as cl
from chainlit.input_widget import Select, TextInput
from agent.shared.logger import get_logger
from web.model_manager import ModelManager
from agent.core.model_config import ModelConfig
from agent.core.team import get_team_instance, reset_team_instance

logger = get_logger("settings_handler")


async def on_settings_update(settings: dict):
    """
    当用户修改设置时触发

    功能：
    1. 获取用户配置的供应商、模型、API Key
    2. 检测供应商是否切换
    3. 如果切换供应商，清空模型列表并提示
    4. 测试 API 连通性
    5. 测试成功后应用配置，失败则不应用
    6. 重新初始化 Team 实例
    7. 更新设置界面的模型列表
    """
    user_session = cl.user_session.get("user_session")
    
    # 获取新的配置（使用 or 确保返回字符串，避免 None.strip() 报错）
    provider = (settings.get("provider") or "").strip()
    model = (settings.get("model_name") or "").strip()
    api_key = (settings.get("api_key") or "").strip()
    
    # 获取旧配置
    old_provider = user_session.current_provider
    
    # 使用界面的 API Key 或环境变量
    test_key = api_key if api_key else ModelConfig.get_api_key()
    
    # 检测供应商是否切换
    provider_changed = old_provider and provider and old_provider != provider
    
    # 检测是否点击了重置选项
    if provider == "--- 重置设置 ---":
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
        
        # 重新发送设置界面（恢复默认）
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["--- 重置设置 ---", "deepseek", "siliconflow"],
                    initial_index=0,  # 默认指向重置
                ),
                Select(
                    id="model_name",
                    label="模型名称",
                    values=["请先配置 API Key 后获取模型列表"],
                    initial_index=0,
                ),
                TextInput(
                    id="api_key",
                    label="API Key（可选）",
                    placeholder="DeepSeek 必需，SiliconFlow 可选",
                    initial="",
                ),
            ]
        ).send()
        
        await cl.Message(
            content="""🔄 **设置已重置为默认值**

💡 请重新配置模型：
1. 选择供应商（DeepSeek 或 SiliconFlow）
2. 输入 API Key（SiliconFlow 可选）
3. 点击保存自动测试连接

⚙️ **当前默认配置：**
- 供应商：deepseek
- API Key：清空
- Team：未初始化（配置后自动初始化）"""
        ).send()
        return
    
    # 如果供应商切换了，先清空模型列表
    if provider_changed:
        # 根据 provider 设置 initial_index（重置选项永远在第一位）
        provider_initial_index = 0
        if provider == "deepseek":
            provider_initial_index = 1
        elif provider == "siliconflow":
            provider_initial_index = 2
        
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["--- 重置设置 ---", "deepseek", "siliconflow"],
                    initial_index=provider_initial_index,
                ),
                Select(
                    id="model_name",
                    label="模型名称",
                    values=["请配置 API Key 后获取模型列表"],
                    initial_index=0,
                ),
                TextInput(
                    id="api_key",
                    label="API Key（可选）",
                    placeholder="DeepSeek 必需，SiliconFlow 可选",
                    initial=api_key or "",
                ),
            ]
        ).send()
        
        await cl.Message(
            content=f"""🔄 **供应商已切换为 {provider.upper()}**

💡 请配置 API Key 后点击保存，自动测试连接并获取模型列表。"""
        ).send()
        return  # 切换供应商后，等待用户再次点击保存
    
    # 如果没有配置 API Key 且选择了 DeepSeek，提示错误
    if provider == "deepseek" and not test_key:
        await cl.Message(
            content="""❌ **DeepSeek 需要配置 API Key**

💡 请在设置界面输入 API Key，或设置环境变量 DEEPSEEK_API_KEY。"""
        ).send()
        return
    
    # 发送测试中消息
    loading_msg = cl.Message(content="🔌 **正在测试连接...**")
    await loading_msg.send()
    
    # 测试连接
    result = await ModelManager.test_connection(provider, test_key)
    
    # 移除加载消息
    await loading_msg.remove()
    
    if result["success"]:
        # 测试成功，应用配置
        # 更新会话状态
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
        
        # 获取最新的模型列表
        models = result.get("models", [])
        
        # 重新发送设置界面（更新模型列表）
        # 根据 provider 设置 initial_index（重置选项永远在第一位）
        provider_initial_index = 0
        if provider == "deepseek":
            provider_initial_index = 1
        elif provider == "siliconflow":
            provider_initial_index = 2
        
        # 计算当前模型的索引
        model_initial_index = 0
        if model and model in models:
            model_initial_index = models.index(model)
        
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["--- 重置设置 ---", "deepseek", "siliconflow"],  # 添加重置选项
                    initial_index=provider_initial_index,
                ),
                Select(
                    id="model_name",
                    label="模型名称",
                    values=models,
                    initial_index=model_initial_index,
                ),
                TextInput(
                    id="api_key",
                    label="API Key（可选）",
                    placeholder="DeepSeek 必需，SiliconFlow 可选",
                    initial=api_key or "",
                ),
            ]
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