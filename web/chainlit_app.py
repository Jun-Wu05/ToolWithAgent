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

=== 重构后（Step 5.7） ===
本文件仅保留 Chainlit 生命周期钩子 + 薄编排逻辑。
业务函数已拆分至:
  - web/route_config.py      路由关键词加载
  - web/llm_client.py        Team 调用 / Token 统计 / 熔断器
  - web/input_builder.py     LLM 输入构建
  - web/response_handler.py  响应解析与表格渲染
  - web/threat_handler.py    威胁填充模式分流与执行
  - web/enum_handler.py      枚举填充/提取分流与执行
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
import json
import io
import logging
from datetime import datetime

# 初始化日志
from agent.shared.logger import get_logger
logger = get_logger("chainlit_app")

# 隐藏第三方库的 DEBUG 日志
logging.getLogger("openai").setLevel(logging.WARNING)	 
logging.getLogger("httpcore").setLevel(logging.WARNING)	 
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("python_multipart").setLevel(logging.WARNING)
 

logger.info("=" * 60)
logger.info("Chainlit聊天式Web应用启动")
logger.info("=" * 60)

# 会话状态管理
from web.session_state import SessionState

# ============= 从拆分模块导入业务函数 =============

# 路由与解析
from web.parsers import parse_json_mapping_result, parse_json_threat_result, create_dataframe_elements
from web.route_config import MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS, ENUM_EXTRACT_KEYWORDS
from web.llm_client import call_team, setup_agno_logging_bridge
from agent.core.tracing import trace_request
from web.input_builder import build_llm_input
from web.response_handler import process_team_response
from web.threat_handler import handle_threat_fill_flow, execute_threat_fill
from web.enum_handler import handle_enum_fill_flow, execute_enum_fill, handle_enum_extract_flow

# 枚举工具（handle_file_upload 中引用）
from agent.tools.enum_field_tool import get_enum_preview

# 加载路由关键词（枚举提取关键词保留，用于枚举提取流触发）



# ============= Chainlit 事件处理 =============

_agno_bridge_installed: bool = False


@cl.on_chat_start
async def start():
    """聊天开始时初始化"""
    # 安装 Agno 日志拦截器（仅一次）
    global _agno_bridge_installed
    if not _agno_bridge_installed:
        setup_agno_logging_bridge()
        _agno_bridge_installed = True

    # 创建用户会话状态（使用结构化 SessionState）
    user_session = SessionState.create_default()
    cl.user_session.set("user_session", user_session)

    # 初始化Team并预热
    try:
        import sys, os
        _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if _root not in sys.path:
            sys.path.insert(0, _root)

        from agent.core.team import get_team_instance
        user_session.team = get_team_instance()
        logger.info("[START] Team初始化成功")
    except ValueError as e:
        logger.error(f"[START] Team初始化失败: {e}")
        await cl.Message(content=f"⚠️ Team初始化失败: {str(e)}").send()
    except Exception as e:
        logger.error(f"[START] Team初始化异常: {e}")
        await cl.Message(content=f"⚠️ Team初始化异常: {str(e)}").send()

    # 发送欢迎消息
    await cl.Message(
        content="""👋 **数据映射智能助手已就绪！**

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

请上传数据文件或直接发送消息开始对话。""",
    ).send()


@cl.on_message
@trace_request("user_request")
async def main(message: cl.Message):
    """
    处理用户消息 - 纯UI层

    Args:
        message: 用户消息，包含文本和可能上传的文件
    """
    user_session = cl.user_session.get("user_session")
    team = user_session.get("team")

    if team is None:
        await cl.Message(content="⚠️ Team未初始化，请刷新页面重新开始").send()
        return

    # 处理上传的文件
    if message.elements:
        for element in message.elements:
            if hasattr(element, 'type') and element.type == "file":
                await handle_file_upload(user_session, element)

    # 处理文本消息
    user_text = message.content.strip()
    if user_text:
        await handle_user_message(user_session, team, user_text)


# ============= 文件处理 =============

async def handle_file_upload(user_session: dict, element):
    """处理文件上传 — 委托给各 handler"""
    try:
        # 获取文件路径并读取内容
        if hasattr(element, 'path') and element.path:
            with open(element.path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
        elif hasattr(element, 'content'):
            file_content = element.content
            if isinstance(file_content, bytes):
                file_content = file_content.decode('utf-8', errors='ignore')
        else:
            file_content = str(element)

        # ========== 威胁填充模式状态隔离 ==========
        if user_session.get("threat_fill_mode"):
            mapping_table = user_session.get("threat_mapping_table")

            if not mapping_table:
                await cl.Message(content="❌ 威胁映射表格丢失，请重新执行威胁类型映射").send()
                user_session["threat_fill_mode"] = False
                return

            # 检查是否已有目标字段名
            target_field = user_session.get("threat_target_field")

            if target_field:
                logger.info(f"[FILE_UPLOAD] 威胁填充模式，有字段名，直接执行填充")
                await execute_threat_fill(user_session, file_content)
            else:
                logger.info(f"[FILE_UPLOAD] 威胁填充模式，无字段名，保存文件到 pending_base64")
                user_session["pending_base64"] = file_content
                await cl.Message(content="📁 **Base64 文件已上传！**\n\n请在下方发送目标字段名（如：original_log）来完成填充。").send()

            return

        # ========== 枚举填充模式状态隔离 ==========
        if user_session.get("enum_fill_mode"):
            enum_excel_path = user_session.get("enum_excel_path")

            if not enum_excel_path:
                await cl.Message(content="❌ 枚举映射表路径丢失，请重新上传Excel映射表").send()
                user_session["enum_fill_mode"] = False
                return

            logger.info(f"[FILE_UPLOAD] 枚举填充模式，执行枚举填充")
            await execute_enum_fill(user_session, file_content)
            return

        # ========== 检测 Excel 枚举映射表 ==========
        file_name = getattr(element, 'name', '') or ''
        if file_name.lower().endswith(('.xlsx', '.xls')):
            logger.info(f"[FILE_UPLOAD] 检测到 Excel 文件: {file_name}")

            # 获取文件路径
            excel_path = getattr(element, 'path', None)
            if not excel_path:
                await cl.Message(content="❌ 无法获取 Excel 文件路径").send()
                return

            try:
                # 读取枚举映射预览
                enum_preview = get_enum_preview(excel_path)

                if not enum_preview:
                    await cl.Message(content="❌ Excel 文件中未找到有效的映射数据").send()
                    return

                # 检查是否有待处理的 Base64 数据（同时上传场景）
                pending_base64 = user_session.get("pending_base64")

                # 保存到会话
                user_session["enum_excel_path"] = excel_path
                user_session["enum_preview"] = enum_preview

                # 获取目标字段列表
                target_fields = list(set(item["目标字段"] for item in enum_preview))

                # 如果有待处理的 Base64，直接执行一站式填充
                if pending_base64:
                    logger.info(f"[FILE_UPLOAD] 检测到同时上传 Excel + Base64，执行一站式填充")

                    # 清除待处理的 Base64
                    user_session["pending_base64"] = None

                    # 设置枚举填充模式并执行
                    user_session["enum_fill_mode"] = True
                    await execute_enum_fill(user_session, pending_base64)
                    return

                # 没有同时上传 Base64，按现有逻辑展示预览
                preview_count = len(enum_preview)
                await cl.Message(
                    content=f"""📊 **枚举映射预览**

📋 **映射统计：**
- 目标字段：{', '.join(target_fields)}
- 映射规则：{preview_count} 条

确认无误后，点击下方按钮开始填充。"""
                ).send()

                # 发送预览 DataFrame
                elements = create_dataframe_elements(enum_preview)
                if elements:
                    await cl.Message(
                        content="**📋 映射预览表：**",
                        elements=elements,
                        actions=[
                            cl.Action(name="start_enum_fill", label="✅ 开始枚举填充", description="上传 Base64 配置文件执行枚举填充", payload={})
                        ]
                    ).send()

                return

            except FileNotFoundError as e:
                await cl.Message(content=f"❌ Excel 文件未找到：{str(e)}").send()
                return
            except Exception as e:
                logger.error(f"[FILE_UPLOAD] Excel 处理异常: {str(e)}")
                await cl.Message(content=f"❌ Excel 文件处理失败：{str(e)}").send()
                return

        # ========== 正常模式：解码 Base64 内容 ==========
        from agent.core.agent import simple_decode
        result = simple_decode(file_content)

        if result["status"] == "success":
            user_session["decoded_data"] = result["decoded_json"]
            user_session["decoded_fields"] = result["fields"]
            user_session["original_log"] = result["original_log"]
            user_session["decoded_text"] = result.get("decoded_text", "")  # 保存解码后的原始文本，供 input_builder 后备使用

            # 构建简化 JSON（只包含必要的索引和日志示例）
            indexes = result.get("fields", [])
            original_log = result.get("original_log", [])
            # 修复：original_log 可能是 string（JSON字符串）、list 或 dict
            if isinstance(original_log, list):
                first_item = original_log[0] if original_log else ""
                # original_log[0] 可能是 dict/list → 转为 JSON 字符串
                if isinstance(first_item, (dict, list)):
                    original_log_sample = json.dumps(first_item, ensure_ascii=False)
                else:
                    original_log_sample = str(first_item) if first_item else ""
            elif isinstance(original_log, str):
                original_log_sample = original_log
            elif isinstance(original_log, dict):
                original_log_sample = json.dumps(original_log, ensure_ascii=False)
            else:
                original_log_sample = str(original_log) if original_log else ""

            simplified_data = {
                "fields": indexes,
                "original_log_sample": original_log_sample
            }
            user_session["simplified_data"] = simplified_data

            # 检查是否有待处理的枚举 Excel 路径（同时上传场景的反向处理）
            enum_excel_path = user_session.get("enum_excel_path")
            enum_preview_ = user_session.get("enum_preview")

            logger.info(f"[FILE_UPLOAD] Base64解码成功，检查枚举状态: enum_excel_path={enum_excel_path is not None}")

            if enum_excel_path and enum_preview_:
                logger.info(f"[FILE_UPLOAD] 检测到已有枚举 Excel + 新上传 Base64，执行一站式填充")

                # 保存到 pending_base64 以防枚举填充失败时可以恢复
                user_session["pending_base64"] = file_content

                # 设置枚举填充模式
                user_session["enum_fill_mode"] = True

                # 执行填充
                await execute_enum_fill(user_session, file_content)
                return

            field_count = result["field_count"]
            await cl.Message(
                content=f"""✅ **文件解码成功！**

📊 **字段数量**：{field_count} 个

现在可以直接发送消息进行字段映射、威胁类型处理等操作。"""
            ).send()
        else:
            await cl.Message(content=f"❌ 解码失败：{result.get('error_message', '未知错误')}").send()

    except Exception as e:
        logger.error(f"文件处理异常: {str(e)}")
        await cl.Message(content=f"❌ 文件处理失败：{str(e)}").send()


# ============= 用户消息处理（主编排）=============

async def handle_user_message(user_session: dict, team, user_text: str):
    """处理用户消息 - 主编排函数，将工作拆分为子函数"""
    import asyncio as asyncio_mod
    import time

    user_lower = user_text.lower()

    # 意图检测（关键词匹配）
    is_enum = any(kw in user_lower for kw in ENUM_KEYWORDS)
    is_enum_extract = any(kw in user_lower for kw in ENUM_EXTRACT_KEYWORDS)
    is_threat = any(kw in user_lower for kw in THREAT_KEYWORDS)
    is_mapping = any(kw in user_lower for kw in MAPPING_KEYWORDS)

    # 1. 威胁填充模式分流 → threat_handler
    if await handle_threat_fill_flow(user_session, user_text):
        return

    # 2. 枚举填充模式分流 → enum_handler
    if await handle_enum_fill_flow(user_session, user_text):
        return

    # 3. 枚举处理分流（当检测到枚举关键词时）
    if is_enum:
        await cl.Message(
            content="""📋 **枚举字段处理**

请上传 **Excel 映射表** 文件来定义枚举映射规则。

Excel 格式说明：
- Sheet 名 = 目标字段名
- 第一列：mappingType（EQUAL 或 REGULAR）
- 第二列：orgValue（原始值）
- 第三列：mappingValue（映射值）

上传后将展示映射预览，确认后可执行填充。"""
        ).send()
        return

    # 4. 枚举提取分流（当检测到枚举提取关键词时）
    if is_enum_extract:
        await handle_enum_extract_flow(user_session, team, user_text)
        return

    # 5. 构建 LLM 输入（按意图隔离上下文）
    # 威胁路由：只传文本，不拼接字段数据（避免旧缓存污染威胁处理）
    # 映射路由：拼接字段数据，供 LLM 做字段映射
    # 通用路由：由 RouterAgent 自己判断
    detected_intent = "general"
    if is_threat:
        detected_intent = "threat"
    elif is_mapping:
        detected_intent = "mapping"
    full_input = build_llm_input(user_text, user_session, intent=detected_intent)

    # 6. 发送 loading 消息
    loading_msg = cl.Message(content="⏳ **AI正在处理中，请稍候...**\n\n💭 正在分析您的请求...")
    await loading_msg.send()

    max_retries = 2
    for retry_attempt in range(max_retries + 1):
        try:
            # 7. 调用 Team → llm_client
            result = await call_team(team, full_input, loading_msg)

            # 8. 删除 loading 消息（重试时不删除，保留状态）
            if retry_attempt == 0:
                await loading_msg.remove()
            else:
                # 重试前更新 loading 消息
                try:
                    loading_msg.content = f"⏳ **AI正在重新分析，请稍候...**\n\n⚠️ 上次未返回有效结果，尝试 {retry_attempt + 1}/{max_retries + 1}"
                    await loading_msg.update()
                except Exception:
                    pass

            # 9. 创建流式消息显示结果
            msg = cl.Message(content="")
            await msg.send()

            # 10. 解析响应 → response_handler
            handled = await process_team_response(result, user_lower, user_session, loading_msg, msg)

            # 11. 如果成功处理，退出重试循环
            if handled:
                # 确保 loading 消息被移除
                try:
                    await loading_msg.remove()
                except Exception:
                    pass
                return

            # 12. 未成功处理（LLM 拒绝响应），记录并重试
            if retry_attempt < max_retries:
                logger.warning(
                    f"[HANDLE] LLM 未返回有效结果（尝试 {retry_attempt + 1}/{max_retries + 1}），"
                    f"强制重试，追加禁止索要数据指令"
                )
                # 在输入中追加强制指令，让 LLM 知道数据已全部提供
                full_input = (
                    f"[SYSTEM NOTE: 所有数据已在上述消息中提供，你不需要也不应该索要任何额外数据。"
                    f"请现在立即使用提供的数据完成处理。禁止输出任何索取性文字。]\n\n{full_input}"
                )
                try:
                    await msg.remove()
                except Exception:
                    pass
            else:
                # 最后一次重试也失败，移除 loading
                try:
                    await loading_msg.remove()
                except Exception:
                    pass
                raise RuntimeError(
                    f"LLM 在 {max_retries + 1} 次尝试中均未返回有效的映射/处理结果，"
                    f"请缩短输入内容或联系管理员。"
                )

        except Exception as e:
            if retry_attempt < max_retries:
                logger.warning(f"Team调用异常 (尝试 {retry_attempt + 1}): {str(e)}，准备重试...")
                await asyncio_mod.sleep(3)
            else:
                logger.error(f"Team调用异常，已达最大重试次数: {str(e)}")
                try:
                    await loading_msg.remove()
                except Exception:
                    pass
                await cl.Message(content=f"❌ 处理异常：{str(e)}").send()
                return


# ============= Action 回调（保留在 chainlit_app.py 中）=============

@cl.action_callback("fill_threat_with_field")
async def on_fill_threat_with_field(action: cl.Action):
    """用户点击"带字段填充"按钮
    [Agent] 进入威胁填充模式，记录映射表格
    """
    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"带字段填充"按钮')

    last_threat_data = user_session.get("last_threat_data")
    logger.info(f"[ACTION] 威胁填充模式，表格数据检查: {last_threat_data is not None}")

    if not last_threat_data:
        await cl.Message(content="❌ 未找到填充数据，请先执行威胁类型映射。").send()
        return

    # 保存表格数据到会话（供威胁填充使用）
    user_session["threat_mapping_table"] = last_threat_data

    # 进入威胁填充模式
    user_session["threat_fill_mode"] = True
    user_session["threat_target_field"] = None
    user_session["pending_base64"] = None

    logger.info(f"[ACTION] 威胁填充模式已激活，映射数量: {len(last_threat_data)}")

    await cl.Message(
        content="""📥 **威胁类型填充模式已开启**

请先发送 **目标字段名**（如：original_log），然后上传 **Base64 配置文件**。

示例：
```
original_log
```
"""
    ).send()


@cl.action_callback("confirm_fill")
async def on_confirm_fill(action: cl.Action):
    """用户点击"确认填充"按钮 — 字段映射填充"""
    user_session = cl.user_session.get("user_session")
    # [Agent] 用户确认填充字段映射结果
    logger.info('[ACTION] 用户点击"确认填充"按钮')

    mapping_data = user_session.get("last_mapping_data")

    if not mapping_data:
        logger.warning("[ACTION] 未找到映射数据")
        await cl.Message(content="❌ 未找到映射数据，请先执行字段映射。").send()
        return

    logger.info(f"[ACTION] 提取字段映射: {len(mapping_data)} 条")

    # 执行字段填充
    try:
        from agent.shared.field_mapping import get_field_mapping_handler
        decoded_data = user_session.get("decoded_data")

        if not decoded_data:
            logger.warning("[ACTION] 未找到原始数据")
            await cl.Message(content="❌ 未找到原始数据，请先上传文件。").send()
            return

        logger.info("[ACTION] 开始执行字段填充")
        handler = get_field_mapping_handler()
        updated_data, update_count = handler.apply_field_mapping(decoded_data, mapping_data)
        logger.info("[ACTION] 字段填充完成")

        # 导出 Base64
        from agent.shared.threat_fill import export_to_base64
        base64_result = export_to_base64(updated_data)

        # 发送下载
        base64_file = cl.File(
            name="field_mapped_config.txt",
            content=base64_result.encode('utf-8'),
            mime="text/plain"
        )
        await cl.Message(
            content=f"✅ **字段填充完成！**\n\n📊 映射了 {update_count} 个字段\n\n📥 点击下载填充后的配置文件：",
            elements=[base64_file]
        ).send()

    except Exception as e:
        logger.error(f"[ACTION] 字段填充异常: {str(e)}")
        await cl.Message(content=f"❌ 填充失败：{str(e)}").send()


@cl.action_callback("start_enum_fill")
async def on_start_enum_fill(action: cl.Action):
    """用户点击"开始枚举填充"按钮
    [Agent] 进入枚举填充模式，等待用户上传 Base64 文件
    """
    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"开始枚举填充"按钮')

    enum_excel_path = user_session.get("enum_excel_path")
    enum_preview = user_session.get("enum_preview")

    if not enum_excel_path or not enum_preview:
        await cl.Message(content="❌ 枚举映射表丢失，请重新上传 Excel 映射表。").send()
        return

    # 设置枚举填充模式
    user_session["enum_fill_mode"] = True

    field_count = len(enum_preview)
    logger.info(f"[ACTION] 枚举填充模式已激活，映射数量: {field_count}")

    await cl.Message(
        content=f"""📋 **枚举填充模式已开启**

映射表：{enum_excel_path}
映射数量：{field_count} 条

请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"""
    ).send()