"""
Chainlit 聊天启动处理器 - 从 chainlit_app.py 提取

本模块处理 @cl.on_chat_start 生命周期事件。
"""

import chainlit as cl
import threading

from chainlit.input_widget import Select, TextInput
from agent.shared.logger import get_logger
from web.session_state import SessionState
from web.llm_client import setup_agno_logging_bridge
from web.global_state import is_agno_bridge_installed, set_agno_bridge_installed

logger = get_logger("start_handler")


async def on_chat_start():
    """
    聊天开始时初始化
    
    职责：
    1. 安装 Agno 日志拦截器（仅一次）
    2. 创建 SessionState 实例
    3. 后台线程初始化语义检索缓存
    4. 渲染模型设置界面（等待用户配置）
    5. 发送欢迎消息
    """
    # 安装 Agno 日志拦截器（仅一次）
    if not is_agno_bridge_installed():
        setup_agno_logging_bridge()
        set_agno_bridge_installed(True)

    # 创建用户会话状态（使用结构化 SessionState）
    user_session = SessionState.create_default()
    cl.user_session.set("user_session", user_session)

    # CHANGED: 启动时不初始化 Team，等用户配置后再初始化
    # 用户首次使用需要先配置模型
    logger.info("[START] 启动时不初始化 Team，等待用户配置")
    
    # 后台线程初始化语义检索 embedding 缓存，不阻塞 Chat 启动
    from agent.core.field_retriever import init_field_cache

    def _background_init_cache() -> None:
        try:
            cache_ready = init_field_cache()
            if cache_ready:
                logger.info("[START] 后台：语义检索缓存就绪")
            else:
                logger.info("[START] 后台：语义检索缓存未就绪，将降级为无候选模式")
        except Exception as bg_e:
            logger.error(f"[START] 后台缓存初始化异常: {bg_e}")

    threading.Thread(target=_background_init_cache, daemon=True, name="cache_init").start()

    # ===== 初始化模型设置界面（启动时不获取模型列表） =====
    # 安全提示：不读取环境变量，不自动保存，每次需要手动输入
    try:
        # 启动时显示空模型列表（等待用户配置）
        # 供应商默认指向重置选项
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["--- 重置设置 ---", "deepseek", "siliconflow"],  # 重置永远第一位
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
                    initial="",  # 不读取环境变量，永远为空
                ),
            ]
        ).send()
        
        logger.info("[START] 模型设置界面已初始化（等待用户配置）")
        
    except Exception as e:
        logger.error(f"[START] 初始化模型设置失败: {e}")
        await cl.Message(
            content=f"⚠️ 模型设置初始化失败：{str(e)}"
        ).send()
    # ===== 初始化结束 =====

    # 发送欢迎消息
    await cl.Message(
        content="""👋 **数据映射智能助手已就绪！**

⚙️ **请先配置模型**
- 点击侧边栏 **"⚙️ 设置"** 按钮
- 选择供应商（DeepSeek 或 SiliconFlow）
- 输入 API Key（每次启动需要重新输入）
- 点击保存自动测试连接

📋 **功能说明：**
- **上传文件**：支持拖拽或点击上传 Base64/TXT/JSON/Excel 文件
- **字段映射**：发送"映射"生成字段映射表
- **威胁类型**：发送"威胁"进行威胁类型标准化
- **枚举处理**：发送"枚举"处理枚举字段

✨ **表格特性：**
- 支持排序（点击列标题）
- 支持筛选
- 支持一键复制
- 支持Excel导出

💡 如需切换文件，发送 **"清空数据"** 即可快速重置会话。

⚠️ **安全提示：**
- API Key 不会自动保存，每次重启需要重新输入
- 请勿在公共设备上使用

请配置模型后上传数据文件或直接发送消息开始对话。"""
    ).send()