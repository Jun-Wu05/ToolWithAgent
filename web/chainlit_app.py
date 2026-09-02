"""
数据映射智能助手 - Chainlit聊天界面

核心特点：
1. 对话式交互，Agent通过聊天与用户沟通
2. 支持在聊天中拖拽上传文件
3. 与Agno Team无缝集成（纯UI层）
4. 使用 cl.Dataframe 展示映射结果，支持排序/筛选/导出

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY 或在.env文件
2. 运行: chainlit run web/chainlit_app.py

=== 重构后（2026-06-12） ===
本文件仅保留 Chainlit 生命周期钩子 + 薄编排逻辑（~50行）。
业务函数已拆分至:
  - web/start_handler.py        @cl.on_chat_start 逻辑
  - web/settings_handler.py     @cl.on_settings_update 逻辑
  - web/message_router.py       @cl.on_message 路由分发
  - web/file_handlers.py        文件上传处理
  - web/user_message_handlers.py 用户文本消息处理
  - web/action_callbacks.py     确定性事件适配
  - web/utils.py                纯辅助函数
"""

# === CRITICAL: 这必须在所有其他导入之前 ===
import sys
import os

# 获取项目根目录（web的父目录）
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)

# 确保项目根目录在sys.path的最前面
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 加载.env文件
from dotenv import load_dotenv
load_dotenv()

import chainlit as cl
import logging

# 初始化日志
from agent.shared.logger import get_logger, initialize_log_retention
logger = get_logger("chainlit_app")

# 启动时清理旧日志（主日志与错误日志分别保留，活动文件不删，删除失败只告警）
initialize_log_retention()

# 隐藏第三方库的 DEBUG 日志
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("python_multipart").setLevel(logging.WARNING)


logger.info("=" * 60)
logger.info("Chainlit聊天式Web应用启动")
logger.info("=" * 60)

# ============= 导入拆分模块 =============
from web.start_handler import on_chat_start
from web.settings_handler import on_settings_update
from web.message_router import on_message

# 注册 Action 回调（必须最后导入，确保所有业务模块已加载）
import web.action_callbacks  # 导入即可，装饰器自动注册


# ============= Chainlit 生命周期钩子 =============

@cl.on_chat_start
async def start():
    """聊天开始时初始化 - 转发到 start_handler"""
    await on_chat_start()


@cl.on_settings_update
async def settings_update(settings: dict):
    """当用户修改设置时触发 - 转发到 settings_handler"""
    await on_settings_update(settings)


@cl.on_message
async def message_handler(message: cl.Message):
    """处理用户消息 - 转发到 message_router"""
    await on_message(message)
