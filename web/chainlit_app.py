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
import logging
from datetime import datetime
from typing import Set

# 初始化日志
from agent.shared.logger import get_logger
logger = get_logger("chainlit_app")

# === 枚举映射表列头关键词（用于区分枚举映射表 vs 数据表格）===
_ENUM_HEADER_KEYWORDS: Set[str] = {
    "mappingtype", "orgvalue", "mappingvalue",
    "原始值", "映射值", "映射类型",
    "目标字段", "target_field", "targetfield"
}

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

# 模型管理
from web.model_manager import ModelManager
from agent.core.model_config import ModelConfig

# Chainlit 输入组件
from chainlit.input_widget import Select, TextInput

# ============= 从拆分模块导入业务函数 =============

# 路由与解析
from web.parsers import parse_json_mapping_result, parse_json_threat_result, create_dataframe_elements
from web.route_config import MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS, ENUM_EXTRACT_KEYWORDS, LOG_PARSER_KEYWORDS
from web.llm_client import call_team, setup_agno_logging_bridge
from agent.core.tracing import trace_request
from web.input_builder import build_llm_input, build_batch_llm_input
from web.response_handler import process_team_response, _check_session_action
from web.threat_handler import handle_threat_fill_flow, execute_threat_fill
from web.enum_handler import handle_enum_fill_flow, execute_enum_fill, handle_enum_extract_flow
from web.file_handler import (
    read_element_content,
    decode_file_content,
    build_simplified_data,
    get_element_file_name,
    process_batched_mapping,
)

# 枚举工具（handle_file_upload 中引用）
from agent.tools.enum_field_tool import get_enum_preview
from agent.tools.log_parser_pipeline import _do_identify_log_format, _do_classify_log_features, fill_sample_logs

# 加载路由关键词（枚举提取关键词保留，用于枚举提取流触发）

# 规则生成模块（入口/子规则生成 + base64 导出 + 标准字段映射）
from agent.tools.rule_generator import (
    generate_rules,
    rules_to_base64_text,
    extract_sub_rule_mapping_info,
    apply_field_mapping_to_sub_rules,
)


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

    # CHANGED: 启动时不初始化 Team，等用户配置后再初始化
    # 用户首次使用需要先配置模型
    logger.info("[START] 启动时不初始化 Team，等待用户配置")
    
    # 后台线程初始化语义检索 embedding 缓存，不阻塞 Chat 启动
    import threading
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
    try:
        # 获取当前供应商
        current_provider = ModelConfig.get_provider()
        env_api_key = ModelConfig.get_api_key()
        
        # 启动时显示空模型列表（等待用户配置）
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["deepseek", "siliconflow"],
                    initial_index=0 if current_provider == "deepseek" else 1,
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
                    initial=env_api_key or "",
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
- 输入 API Key（SiliconFlow 可选）
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

请配置模型后上传数据文件或直接发送消息开始对话。"""
    ).send()


@cl.on_settings_update
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
    
    # 获取新的配置
    provider = settings.get("provider", "").strip()
    model = settings.get("model_name", "").strip()
    api_key = settings.get("api_key", "").strip()
    
    # 获取旧配置
    old_provider = user_session.current_provider
    
    # 使用界面的 API Key 或环境变量
    test_key = api_key if api_key else ModelConfig.get_api_key()
    
    # 检测供应商是否切换
    provider_changed = old_provider and provider and old_provider != provider
    
    # 如果供应商切换了，先清空模型列表
    if provider_changed:
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["deepseek", "siliconflow"],
                    initial_index=0 if provider == "deepseek" else 1,
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
        from agent.core.team import get_team_instance, reset_team_instance
        reset_team_instance()
        user_session.team = get_team_instance()
        
        logger.info("[SETTINGS] Team 已重新初始化")
        
        # 获取最新的模型列表
        models = result.get("models", [])
        
        # 重新发送设置界面（更新模型列表）
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["deepseek", "siliconflow"],
                    initial_index=0 if provider == "deepseek" else 1,
                ),
                Select(
                    id="model_name",
                    label="模型名称",
                    values=models,
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

def _is_enum_mapping_excel(excel_path: str) -> bool:
    """
    通过列头判断 Excel 是否为枚举映射表（而非数据表格）。
    
    Args:
        excel_path: Excel 文件路径
    
    Returns:
        True 如果列头匹配枚举映射表关键词，False 表示是普通数据表格
    """
    try:
        from openpyxl import load_workbook
        wb = load_workbook(excel_path, read_only=True)
        try:
            if not wb.sheetnames:
                return False
            ws = wb[wb.sheetnames[0]]
            # 读取第一行列头
            row1_cells = [cell for cell in ws[1] if cell.value is not None]
            if not row1_cells:
                return False
            row1_headers = {str(cell.value).strip().lower() for cell in row1_cells if str(cell.value).strip()}
            # 判断是否包含枚举映射表关键词
            return bool(row1_headers & _ENUM_HEADER_KEYWORDS)
        finally:
            wb.close()
    except Exception as e:
        logger.warning(f"[ENUM_DETECT] 枚举表头检测异常，回退为数据表格: {e}")
        return False


async def handle_file_upload(user_session: dict, element):
    """处理文件上传 — 委托给各 handler"""
    try:
        # 获取文件内容（委托 file_handler）
        file_content = read_element_content(element)

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
                # 通过列头检测区分枚举映射表 vs 数据表格（避免 get_enum_preview 误判）
                is_enum_table = _is_enum_mapping_excel(excel_path)
                logger.info(f"[FILE_UPLOAD] Excel 表头检测: is_enum_table={is_enum_table}, file={file_name}")

                if not is_enum_table:
                    # 不是枚举映射表 → 直接读取为数据表格，供 LogParserAgent 等下游使用
                    logger.info(f"[FILE_UPLOAD] Excel 列头不匹配枚举映射表，按数据表格处理: {file_name}")
                    try:
                        import pandas as pd
                        df = pd.read_excel(excel_path)
                        if df.empty:
                            await cl.Message(content=f"⚠️ Excel 文件 `{file_name}` 为空，无法读取数据。").send()
                            return
                        # 将 DataFrame 转为结构化数据，填入 user_session（与 Base64 解码流程对齐）
                        records = df.fillna("").to_dict(orient="records")
                        fields = list(df.columns)
                        # original_log 必须是字符串列表（enum_handler 中使用 '\n'.join() 拼接）
                        original_log = [json.dumps(r, ensure_ascii=False) for r in records]
                        decoded_text = df.to_string(index=False)
                        user_session["original_log"] = original_log
                        user_session["decoded_data"] = records
                        user_session["decoded_fields"] = fields
                        user_session["decoded_text"] = decoded_text
                        user_session["simplified_data"] = {
                            "fields": fields,
                            "original_log_sample": decoded_text[:2000]
                        }
                        user_session["uploaded_file_name"] = file_name
                        user_session["uploaded_file_time"] = datetime.now().strftime("%H:%M:%S")
                        # 保存路径供枚举填充等后续使用
                        user_session["enum_excel_path"] = excel_path
                        # 检测"原始日志"列并预提取，供 LogParserAgent 精简输入使用
                        raw_log_lines = None
                        for col in df.columns:
                            if "原始日志" in str(col):
                                raw_log_lines = df[col].dropna().astype(str).tolist()
                                user_session["raw_log_lines"] = raw_log_lines
                                logger.info(f"[FILE_UPLOAD] 提取\"原始日志\"列({col})：{len(raw_log_lines)} 行")
                                break
                        await cl.Message(
                            content=f"📊 已读取 Excel 文件 `{file_name}`\n\n"
                                    f"📊 **行数**：{len(df)} 行\n"
                                    f"📊 **列数**：{len(fields)} 列\n"
                                    f"📊 **列名**：{', '.join(fields[:20])}"
                                    f"{'...' if len(fields) > 20 else ''}"
                                    + (f"\n📊 **原始日志**：{len(raw_log_lines)} 行" if raw_log_lines else "")
                        ).send()
                        logger.info(f"[FILE_UPLOAD] Excel 数据表格读取成功：{len(df)} 行 × {len(fields)} 列")
                        return
                    except ImportError:
                        logger.error("[FILE_UPLOAD] pandas 未安装，无法读取 Excel 数据")
                        await cl.Message(content="⚠️ 系统缺少 Excel 解析库 (pandas)，请联系管理员。").send()
                        return
                    except Exception as excel_read_err:
                        logger.error(f"[FILE_UPLOAD] 读取 Excel 数据表格失败: {excel_read_err}")
                        await cl.Message(content=f"⚠️ 读取 Excel 文件失败：{excel_read_err}").send()
                        return

                # 是枚举映射表 → 读取枚举映射预览
                enum_preview = get_enum_preview(excel_path)
                logger.info(f"[FILE_UPLOAD] 枚举映射表确认，预览条数: {len(enum_preview) if enum_preview else 0}")

                if not enum_preview:
                    await cl.Message(content=f"⚠️ 枚举映射表 `{file_name}` 未读取到有效映射规则").send()
                    return

                # 保存到会话
                user_session["enum_excel_path"] = excel_path
                user_session["enum_preview"] = enum_preview

                # 获取目标字段列表
                target_fields = list(set(item["目标字段"] for item in enum_preview))

                # 展示预览，枚举填充交由 handle_user_message 的路由触发
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
        # 委托 file_handler 处理解码
        result = decode_file_content(file_content)

        if result["status"] == "success":
            user_session["decoded_data"] = result["decoded_json"]
            user_session["decoded_fields"] = result["fields"]
            user_session["original_log"] = result["original_log"]
            user_session["decoded_text"] = result.get("decoded_text", "")

            # 记录上传文件元信息
            file_name_val = get_element_file_name(element)
            user_session["uploaded_file_name"] = file_name_val
            user_session["uploaded_file_time"] = datetime.now().strftime("%H:%M:%S")
            logger.info(f"[FILE_UPLOAD] 记录上传文件元信息: name={file_name_val}, time={user_session['uploaded_file_time']}")

            # 构建 simplified_data（委托 file_handler）
            user_session["simplified_data"] = build_simplified_data(result)

            # 缓存原始 Base64 内容，供枚举填充等后续操作使用
            user_session["raw_base64"] = file_content

            # 检查是否有待处理的枚举 Excel 路径（同时上传场景的反向处理）
            enum_excel_path = user_session.get("enum_excel_path")
            enum_preview_ = user_session.get("enum_preview")

            logger.info(f"[FILE_UPLOAD] Base64解码成功，raw_base64已缓存，enum_excel_path={enum_excel_path is not None}")

            # 枚举填充由 handle_user_message 路由统一触发，此处不再自动执行

            field_count = result["field_count"]
            original_log = result.get("original_log")
            log_line_count = len(original_log) if original_log and isinstance(original_log, list) else 0

            stats_lines = [f"**字段数量**：{field_count} 个"]
            if log_line_count > 0:
                stats_lines.append(f"**日志行数**：{log_line_count} 行")
            stats_text = "\n".join(f"📊 {line}" for line in stats_lines)

            await cl.Message(
                content=f"""✅ **文件解码成功！**

{stats_text}

💡 如需处理其他文件，请输入 **"清空数据"** 或 **"切换文件"** 快速重置
现在可以进行字段映射、威胁类型、枚举提取等操作。"""
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

    # ====== P2 问题3：记录用户输入 ======
    logger.info(f"[USER_INPUT] 用户消息: {user_text[:500]}")
    # ====================================

    user_lower = user_text.lower()

    # ====== 清空/切换数据快捷路径（P2优化：避免LLM处理，秒级响应） ======
    _clear_keywords = ("清空", "切换数据", "新文件", "换一个", "换文件",
                       "重新上传", "丢弃", "丢掉", "清除数据", "clear", "reset",
                       "从头开始", "新建", "重开")
    if any(kw in user_lower for kw in _clear_keywords):
        logger.info(f"[SHORTCUT] 检测到清空/切换数据意图: {user_text[:100]}，执行快捷清空")
        # 清空解码数据
        if hasattr(user_session, "clear_decoded_data"):
            user_session.clear_decoded_data()
        else:
            for key in ["decoded_data", "decoded_fields", "simplified_data",
                         "decoded_text", "original_log", "uploaded_file_name",
                         "uploaded_file_time", "last_mapping_data", "last_threat_data"]:
                user_session.pop(key, None)
        await cl.Message(
            content="🗑️ **数据已清空** — 请上传新文件继续处理。"
        ).send()
        return
    # ====================================================================

    # 意图检测（关键词匹配）
    is_enum = any(kw in user_lower for kw in ENUM_KEYWORDS)
    is_enum_extract = any(kw in user_lower for kw in ENUM_EXTRACT_KEYWORDS)
    is_threat = any(kw in user_lower for kw in THREAT_KEYWORDS)
    is_mapping = any(kw in user_lower for kw in MAPPING_KEYWORDS)
    is_log_parser = any(kw in user_lower for kw in LOG_PARSER_KEYWORDS)

    # 1. 威胁填充模式分流 → threat_handler
    if await handle_threat_fill_flow(user_session, user_text):
        return

    # 2. 枚举填充模式分流 → enum_handler
    if await handle_enum_fill_flow(user_session, user_text):
        return

    # 2.5 枚举填充自动触发：同时存在 raw_base64 + enum_excel_path 则直接执行填充
    if user_session.get("enum_excel_path") and any(kw in user_lower for kw in ENUM_KEYWORDS):
        raw_base64 = user_session.get("raw_base64")

        if raw_base64:
            user_session["enum_fill_mode"] = True
            logger.info("[ROUTE] raw_base64 + enum_excel_path 同时存在，自动触发枚举填充")
            await execute_enum_fill(user_session, raw_base64)
            return

        # 有 Excel 但无 Base64：提示上传
        user_session["enum_fill_mode"] = True
        logger.info("[ROUTE] 检测到已有枚举Excel，激活填充模式，等待Base64上传")
        await cl.Message(
            content=f"""📋 **枚举填充模式已激活**

已选择映射表：{user_session.get('enum_excel_path')}

请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"""
        ).send()
        return

    # 3. 枚举提取分流（精确匹配优先：含"提取"/"列举"/"列出"等词）
    if is_enum_extract:
        await handle_enum_extract_flow(user_session, team, user_text)
        return

    # 4. 枚举处理分流（宽泛匹配：仅含"枚举"但无提取意图）
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

    # 4.5 日志解析分流
    if is_log_parser:
        logger.info("[ROUTE] 命中日志解析关键词，直接调用 Pipeline（跳过 Agent 路由）")
        loading_msg = cl.Message(content="⏳ **AI正在分析日志，请稍候...**\n\n🔍 正在识别格式并提取特征...")
        await loading_msg.send()
        try:
            # 获取原始日志文本
            raw_log_lines = user_session.get("raw_log_lines")
            if raw_log_lines:
                # CHANGED: 移除 [:200] 截断，让 _aggregate_by_log_type 能发现低频日志类型（如 ssoaccess）
                # 内部函数（identify/classify）已各自采样 3~5 行供 LLM，无需外部截断
                logs_str = "\n".join(str(line) for line in raw_log_lines)
                logger.info(f"[ROUTE][LogParser] 使用完整输入：{len(raw_log_lines)} 行原始日志")
            else:
                logs_str = user_text
                logger.info(f"[ROUTE][LogParser] 无 raw_log_lines，回退使用 user_text")

            # Step 1: 格式识别
            logger.info("[ROUTE][LogParser] Step 1: identify_log_format")
            format_info_str = _do_identify_log_format(logs_str)
            format_info = _parse_json_safe(format_info_str)
            format_type = format_info.get("format", "unknown") if isinstance(format_info, dict) else "unknown"
            format_detail = format_info.get("format_detail", "") if isinstance(format_info, dict) else ""
            # feature_field 由 Step 1 (log_format_identifier) 中 LLM 识别，Step 2 中使用
            feature_field = format_info.get("feature_field", "log_type") if isinstance(format_info, dict) else "log_type"
            header_end_marker = format_info.get("header_end_marker", "") if isinstance(format_info, dict) else ""
            logger.info(f"[ROUTE][LogParser] 格式识别结果: format={format_type}, detail={format_detail}, header_end_marker='{header_end_marker}'")

            # Step 2: 特征分类
            # CHANGED (2026-05-29): 路由逻辑已内置到 _do_classify_log_features 中
            # （含 Step 2a 特征定位 → Path A / Path Main），无需在 chainlit_app 层判断
            logger.info("[ROUTE][LogParser] Step 2: classify_log_features (统一入口)")
            classification_str = _do_classify_log_features(
                logs_str=logs_str,
                format_type=format_type,
                format_detail=format_detail,
                feature_field=feature_field,
                format_info=format_info if isinstance(format_info, str) else json.dumps(format_info, ensure_ascii=False),
                header_end_marker=header_end_marker,
            )
            classification = _parse_json_safe(classification_str)

            # Step 3: 用 feature_identifier 替换真实样例
            logger.info("[ROUTE][LogParser] Step 3: fill_sample_logs")
            if isinstance(classification, dict):
                classification = fill_sample_logs(
                    classification, logs_str,
                )

            # 保存分类结果到会话（供规则导出使用）
            user_session["log_classification"] = classification

            # 渲染结果
            result_content = _render_log_parser_result(classification, format_info)
        except Exception as e:
            logger.error(f"[ROUTE][LogParser] Pipeline 异常: {type(e).__name__}: {e}")
            result_content = f"❌ 日志解析失败: {e}"
            classification = None
        finally:
            try:
                await loading_msg.remove()
            except Exception:
                pass
        await cl.Message(
            content=result_content,
            actions=[
                cl.Action(
                    name="export_rules",
                    label="📥 导出入口规则",
                    description="生成入口分发规则并导出 base64",
                    payload={}
                ),
                cl.Action(
                    name="export_sub_rules",
                    label="📥 导出子规则",
                    description="生成子类分发规则并导出 base64",
                    payload={}
                ),
                cl.Action(
                    name="apply_field_mapping",
                    label="🔍 标准字段映射",
                    description="对子规则进行标准字段映射分析",
                    payload={}
                ),
            ],
        ).send()
        # 附加完整 JSON 文件下载
        if classification and isinstance(classification, dict):
            try:
                json_bytes = json.dumps(classification, ensure_ascii=False, indent=2).encode("utf-8")
                json_file = cl.File(
                    name="日志解析结果.json",
                    content=json_bytes,
                    mime="application/json",
                )
                await cl.Message(content="📥 **完整结果下载：**", elements=[json_file]).send()
            except Exception as json_err:
                logger.error(f"[ROUTE][LogParser] 生成 JSON 下载文件失败: {json_err}")
        return

    # 5. 构建 LLM 输入（按意图隔离上下文）
    # 威胁路由：只传文本，不拼接字段数据（避免旧缓存污染威胁处理）
    # 映射路由：拼接字段数据，供 LLM 做字段映射
    # 日志解析路由：由 RouterAgent 路由到 LogParserAgent
    # 通用路由：由 RouterAgent 自己判断
    detected_intent = "general"
    if is_threat:
        detected_intent = "threat"
    elif is_mapping:
        detected_intent = "mapping"
    elif is_log_parser:
        detected_intent = "log_parser"

    # ====== P2 自动分批：字段 > 25 时分批调用，避免超时 ======
    BATCH_SIZE = 25
    if detected_intent == "mapping":
        fields_list = user_session.get("simplified_data", {}).get("fields", [])
        if len(fields_list) > BATCH_SIZE:
            import math
            total_batches_preview = math.ceil(len(fields_list) / BATCH_SIZE)
            logger.info(f"[BATCH] 字段数 {len(fields_list)} > {BATCH_SIZE}，进入分批模式，共 {total_batches_preview} 批")

            loading_msg = cl.Message(content=f"⏳ **正在处理字段映射（第 1/{total_batches_preview} 批）...**")
            await loading_msg.send()

            # 委托 file_handler.process_batched_mapping 执行分批调用
            # 构建回调适配器
            def build_batch_fn(u_text, u_sess, batch, idx, total):
                return build_batch_llm_input(u_text, u_sess, batch, idx, total)

            async def call_team_fn(t, input_text, _loading, intent):
                return await call_team(t, input_text, loading_msg, intent=intent)

            async def on_batch_complete(batch_idx: int, total: int, batch_count: int, total_count: int):
                loading_msg.content = f"⏳ **正在处理字段映射（第 {batch_idx + 1}/{total} 批）...**"
                try:
                    await loading_msg.update()
                except Exception:
                    pass

            from web.file_handler import process_batched_mapping
            all_mapping_data, total_batches = await process_batched_mapping(
                team=team,
                fields_list=fields_list,
                user_text=user_text,
                user_session=user_session,
                build_batch_fn=build_batch_fn,
                call_team_fn=call_team_fn,
                parse_fn=parse_json_mapping_result,
                batch_size=BATCH_SIZE,
                on_batch_complete=on_batch_complete,
            )

            try:
                await loading_msg.remove()
            except Exception:
                pass

            if all_mapping_data:
                user_session["last_mapping_data"] = all_mapping_data
                matched_count = sum(1 for item in all_mapping_data if item.get("匹配状态") == "匹配成功")
                unmatched_count = len(all_mapping_data) - matched_count

                # CHANGED: 保存批量映射数据供 Excel 导出使用（转换为 sub_rule_mapping_results 格式）
                # 包装成与 on_apply_field_mapping 兼容的格式
                batch_mapping_results = [{
                    "rule_name": "批量映射",
                    "mappings": [
                        {
                            "原始字段名": item.get("原始字段名", ""),
                            "系统属性名称": item.get("系统属性名称", ""),
                            "匹配状态": item.get("匹配状态", "")
                        }
                        for item in all_mapping_data
                    ]
                }]
                user_session["batch_mapping_results"] = batch_mapping_results

                summary = f"""✅ **字段映射完成！（分 {total_batches} 批处理）**

📊 **映射统计：**
- 总字段数：{len(all_mapping_data)}
- 匹配成功：{matched_count} 个
- 未匹配：{unmatched_count} 个

✨ **表格功能：**
- 📌 点击列标题排序
- 🔍 使用搜索框筛选
- ✏️ 点击单元格编辑系统属性名称
- 📥 导出CSV文件"""

                msg = cl.Message(content="")
                await msg.send()
                for i in range(0, len(summary), 50):
                    await msg.stream_token(summary[i:i + 50])
                await msg.update()

                elements = create_dataframe_elements(all_mapping_data)
                if elements:
                    await cl.Message(
                        content="**📋 字段映射表：**\n\n请确认映射结果，点击下方按钮填充到原始数据中。",
                        elements=elements,
                        actions=[
                            cl.Action(name="confirm_fill", label="✅ 确认填充", description="确认后将映射结果填充到原始数据", payload={}),
                            cl.Action(
                                name="export_batch_field_mapping_excel",
                                label="📥 导出字段映射 Excel",
                                description="下载字段映射表为 Excel 文件",
                                payload={}
                            ),
                        ]
                    ).send()
                return
            else:
                await cl.Message(content="❌ 所有批次均未返回有效映射结果，请缩短输入内容或联系管理员。").send()
                return
    # ====================================================================

    full_input = build_llm_input(user_text, user_session, intent=detected_intent)

    # 6. 发送 loading 消息
    loading_msg = cl.Message(content="⏳ **AI正在处理中，请稍候...**\n\n💭 正在分析您的请求...")
    await loading_msg.send()

    max_retries = 2
    for retry_attempt in range(max_retries + 1):
        try:
            # 7. 调用 Team → llm_client（传递 intent 跳过 RouterAgent）
            result = await call_team(team, full_input, loading_msg, intent=detected_intent)

            # 7.5 Agent 自决清空：检测 [SESSION_ACTION:clear] 标记
            result_content = result.content if hasattr(result, 'content') else str(result)
            session_action_cleared = await _check_session_action(result_content, user_session, loading_msg)
            if session_action_cleared:
                # Agent 判定需要清空会话，已通过 _check_session_action 发送通知
                try:
                    await loading_msg.remove()
                except Exception:
                    pass
                return

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

        except asyncio_mod.TimeoutError as e:
            logger.error(f"Team调用超时: {e}")
            try:
                await loading_msg.remove()
            except Exception:
                pass
            await cl.Message(
                content=f"⏰ **请求超时**\n\nLLM 在 120 秒内未返回结果，请稍后重试。\n\n"
                        f"建议：减少上传数据量或检查网络连接。"
            ).send()
            return

        except Exception as e:
            logger.error(f"Team调用异常: {e}")
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

请先发送 **目标字段名**（如：threat_type），然后上传 **Base64 配置文件**。

示例：
```
threat_type
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


# ============= 规则导出 Action 回调 =============

@cl.action_callback("export_rules")
async def on_export_rules(action: cl.Action):
    """用户点击"📥 导出入口规则"按钮 — 从分类结果生成入口分发规则并导出 base64"""
    user_session = cl.user_session.get("user_session")
    classification = user_session.get("log_classification")
    logger.info('[ACTION] 用户点击"导出入口规则"按钮')

    if not classification or not isinstance(classification, dict):
        await cl.Message(content="❌ 未找到日志分类结果，请先执行日志解析。").send()
        return

    try:
        logger.info("[ACTION] 调用 generate_rules(mode='entry')")
        result = generate_rules(classification, mode="entry")
        if not result.get("success"):
            await cl.Message(content=f"❌ 入口规则生成失败：{result.get('error', '未知错误')}").send()
            return

        base64_text = rules_to_base64_text(result.get("rules", []))
        file_name = result.get("file_name", "entry_rules.txt")

        base64_file = cl.File(name=file_name, content=base64_text, mime="text/plain")
        await cl.Message(
            content=f"✅ 入口规则已生成！共 {result.get('rule_count', 0)} 条规则。\n\n📥 点击下载：",
            elements=[base64_file],
        ).send()
    except Exception as e:
        logger.error(f"[ACTION] 入口规则导出异常: {e}")
        await cl.Message(content=f"❌ 入口规则导出失败：{e}").send()


@cl.action_callback("export_sub_rules")
async def on_export_sub_rules(action: cl.Action):
    """用户点击"📥 导出子规则"按钮 — 从分类结果生成子类分发规则并导出 base64"""
    user_session = cl.user_session.get("user_session")
    classification = user_session.get("log_classification")
    logger.info('[ACTION] 用户点击"导出子规则"按钮')

    if not classification or not isinstance(classification, dict):
        await cl.Message(content="❌ 未找到日志分类结果，请先执行日志解析。").send()
        return

    try:
        logger.info("[ACTION] 调用 generate_rules(mode='sub')")
        result = generate_rules(classification, mode="sub")
        if not result.get("success"):
            await cl.Message(content=f"❌ 子规则生成失败：{result.get('error', '未知错误')}").send()
            return

        base64_text = rules_to_base64_text(result.get("rules", []))
        file_name = result.get("file_name", "sub_rules.txt")

        base64_file = cl.File(name=file_name, content=base64_text, mime="text/plain")
        await cl.Message(
            content=f"✅ 子规则已生成！共 {result.get('rule_count', 0)} 条规则。\n\n📥 点击下载：",
            elements=[base64_file],
        ).send()
    except Exception as e:
        logger.error(f"[ACTION] 子规则导出异常: {e}")
        await cl.Message(content=f"❌ 子规则导出失败：{e}").send()


# ============= 标准字段映射 Action 回调 =============

@cl.action_callback("apply_field_mapping")
async def on_apply_field_mapping(action: cl.Action):
    """用户点击「🔍 标准字段映射」—— 复用路径1逻辑，并行处理"""
    user_session = cl.user_session.get("user_session")
    classification = user_session.get("log_classification")
    logger.info('[ACTION] 用户点击"标准字段映射"按钮')

    if not classification or not isinstance(classification, dict):
        await cl.Message(content="❌ 未找到日志分类结果，请先执行日志解析。").send()
        return

    try:
        # 1. 生成子规则（用于获取字段列表）
        logger.info("[ACTION] 生成子规则用于字段映射")
        from agent.tools.rule_generator import generate_sub_rules
        
        # 获取完整日志字符串（用于聚合字段）
        raw_log_lines = user_session.get("raw_log_lines", [])
        all_logs_str = "\n".join(str(line) for line in raw_log_lines) if raw_log_lines else ""
        
        sub_rules = generate_sub_rules(classification, all_logs_str=all_logs_str)

        if not sub_rules:
            await cl.Message(content="❌ 未生成任何子规则，无法进行字段映射。").send()
            return

        # 2. 提取所有字段（不区分子规则）
        all_fields = []
        for rule in sub_rules:
            fields = [
                entry.get("index", "")
                for entry in rule.get("normalize", [])
                if entry.get("index", "") not in ("original_log", "日志类型")
            ]
            all_fields.extend(fields)
        
        # 去重
        all_fields = list(set(all_fields))
        all_fields.sort()  # 排序，保证顺序一致
        
        logger.info(f"[ACTION] 共提取 {len(all_fields)} 个唯一字段")

        # 3. 添加日志样例（直接使用原始日志文本）
        sample_logs_text = "\n".join(str(line) for line in raw_log_lines[:10]) if raw_log_lines else ""
        simplified_data = {
            "fields": all_fields,
            "original_log_sample": sample_logs_text
        }
        user_session["simplified_data"] = simplified_data

        # 4. 直接调用路径1的 process_batched_mapping（并行处理）
        logger.info(f"[ACTION] 开始标准字段映射，字段数: {len(all_fields)}")
        
        BATCH_SIZE = 25
        
        def build_batch_fn(u_text, u_sess, batch, idx, total):
            return build_batch_llm_input(u_text, u_sess, batch, idx, total)

        async def call_team_fn(t, input_text, _loading, intent):
            return await call_team(t, input_text, loading_msg, intent=intent)

        async def on_batch_complete(batch_idx: int, total: int, batch_count: int, total_count: int):
            loading_msg.content = f"⏳ **正在处理字段映射（第 {batch_idx + 1}/{total} 批）...**"
            try:
                await loading_msg.update()
            except Exception:
                pass

        loading_msg = cl.Message(content="⏳ **正在处理字段映射...**")
        await loading_msg.send()

        mapping_data, total_batches = await process_batched_mapping(
            team=user_session.get("team"),
            fields_list=all_fields,
            user_text="标准字段映射",
            user_session=user_session,
            build_batch_fn=build_batch_fn,
            call_team_fn=call_team_fn,
            parse_fn=parse_json_mapping_result,
            batch_size=BATCH_SIZE,
            on_batch_complete=on_batch_complete,
        )

        try:
            await loading_msg.remove()
        except Exception:
            pass

        if not mapping_data:
            await cl.Message(content="❌ 字段映射失败，请重试。").send()
            return

        # 5. 将结果按子规则分组（用于展示）
        field_to_mapping = {
            item.get("原始字段名", ""): item
            for item in mapping_data
        }
        
        all_sub_rule_results = []
        for rule in sub_rules:
            rule_name = rule.get("name", "")
            rule_fields = [
                entry.get("index", "")
                for entry in rule.get("normalize", [])
                if entry.get("index", "") not in ("original_log", "日志类型")
            ]
            
            rule_mappings = []
            for field in rule_fields:
                mapping = field_to_mapping.get(field)
                if mapping:
                    rule_mappings.append({
                        "原始字段名": mapping.get("原始字段名", ""),
                        "系统属性名称": mapping.get("系统属性名称", ""),
                        "匹配状态": mapping.get("匹配状态", "")
                    })
            
            all_sub_rule_results.append({
                "rule_name": rule_name,
                "mappings": rule_mappings
            })

        # 6. 保存到 session state
        user_session["sub_rule_mapping_results"] = all_sub_rule_results
        
        # 7. 应用映射到子规则（用于导出）
        from agent.tools.standard_mapper import _load_object_mapping
        import os
        excel_path = os.path.join(os.getcwd(), "config", "对象.xlsx")
        object_entity_map = _load_object_mapping(excel_path)
        
        mapped_sub_rules = apply_field_mapping_to_sub_rules(
            sub_rules, all_sub_rule_results, object_entity_map
        )
        
        user_session["mapped_sub_rules"] = mapped_sub_rules
        logger.info(f"[ACTION] 映射后的子规则已保存，共 {len(mapped_sub_rules)} 条")
        
        # 8. 展示结果
        total_matched = 0
        total_fields = 0
        flat_mappings = []
        
        for mr in all_sub_rule_results:
            rule_name = mr.get("rule_name", "未知")
            for m in mr.get("mappings", []):
                flat_mappings.append({
                    "子规则": rule_name,
                    "原始字段": m.get("原始字段名", ""),
                    "标准字段": m.get("系统属性名称", ""),
                    "匹配状态": m.get("匹配状态", ""),
                })
                total_fields += 1
                if "匹配成功" in m.get("匹配状态", ""):
                    total_matched += 1

        summary = (
            f"✅ **标准字段映射完成！**\n\n"
            f"📊 **映射统计：**\n"
            f"- 子规则数量：{len(all_sub_rule_results)}\n"
            f"- 总字段数：{total_fields}\n"
            f"- 匹配成功：{total_matched} 个\n"
            f"- 未匹配：{total_fields - total_matched} 个\n\n"
            f"✨ **表格功能：**\n"
            f"- 📌 点击列标题排序\n"
            f"- 🔍 使用搜索框筛选\n\n"
            f"💡 点击下方按钮导出结果。"
        )

        elements = create_dataframe_elements(flat_mappings)
        await cl.Message(
            content=summary,
            elements=elements,
            actions=[
                cl.Action(
                    name="export_field_mapping_excel",
                    label="📥 导出字段映射 Excel",
                    description="下载字段映射表为 Excel 文件",
                    payload={}
                ),
                cl.Action(
                    name="export_mapped_sub_rules",
                    label="📥 导出映射后子规则",
                    description="导出带标准字段映射的子规则",
                    payload={}
                ),
            ],
        ).send()

    except Exception as e:
        logger.error(f"[ACTION] 标准字段映射异常: {e}")
        await cl.Message(content=f"❌ 标准字段映射失败：{e}").send()


@cl.action_callback("export_mapped_sub_rules")
async def on_export_mapped_sub_rules(action: cl.Action):
    """导出带标准字段映射的子规则"""
    user_session = cl.user_session.get("user_session")
    mapped_sub_rules = user_session.get("mapped_sub_rules")
    logger.info('[ACTION] 用户点击"导出映射后子规则"按钮')

    if not mapped_sub_rules:
        await cl.Message(content="❌ 未找到映射后的子规则，请先执行标准字段映射。").send()
        return

    try:
        base64_text = rules_to_base64_text(mapped_sub_rules)
        date_str = datetime.now().strftime("%Y%m%d")
        file_name = f"映射后子规则_{date_str}.txt"

        base64_file = cl.File(name=file_name, content=base64_text, mime="text/plain")
        await cl.Message(
            content=f"✅ 映射后子规则已导出！共 {len(mapped_sub_rules)} 条规则。\n\n📥 点击下载：",
            elements=[base64_file],
        ).send()
    except Exception as e:
        logger.error(f"[ACTION] 映射后子规则导出异常: {e}")
        await cl.Message(content=f"❌ 导出失败：{e}").send()


@cl.action_callback("export_field_mapping_excel")
async def on_export_field_mapping_excel(action: cl.Action):
    """导出字段映射结果为 Excel 文件（日志解析→标准字段映射路径）"""
    user_session = cl.user_session.get("user_session")
    mapping_results = user_session.get("sub_rule_mapping_results")
    logger.info('[ACTION] 用户点击"导出字段映射 Excel"按钮')

    if not mapping_results:
        await cl.Message(content="❌ 未找到字段映射结果，请先执行标准字段映射。").send()
        return

    try:
        # 构建 Excel 数据
        excel_data = []
        for mr in mapping_results:
            rule_name = mr.get("rule_name", "未知")
            for m in mr.get("mappings", []):
                excel_data.append({
                    "子规则": rule_name,
                    "原始字段": m.get("原始字段名", ""),
                    "标准字段": m.get("系统属性名称", ""),
                    "匹配状态": m.get("匹配状态", ""),
                })

        # 使用 pandas 转换为 Excel
        import pandas as pd
        import io
        
        df = pd.DataFrame(excel_data)
        
        # 创建 Excel 文件内容
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='字段映射')
        
        output.seek(0)
        
        # 生成文件名
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"字段映射_{date_str}.xlsx"
        
        # 发送 Excel 文件
        excel_file = cl.File(
            name=file_name,
            content=output.getvalue(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        await cl.Message(
            content=f"✅ 字段映射表已导出！共 {len(excel_data)} 条映射。\n\n📥 点击下载：",
            elements=[excel_file],
        ).send()
        
    except ImportError:
        logger.error("[ACTION] pandas 或 openpyxl 未安装")
        await cl.Message(content="❌ 系统缺少 Excel 导出库 (pandas/openpyxl)，请联系管理员。").send()
    except Exception as e:
        logger.error(f"[ACTION] 字段映射 Excel 导出异常: {e}")
        await cl.Message(content=f"❌ Excel 导出失败：{e}").send()


@cl.action_callback("export_batch_field_mapping_excel")
async def on_export_batch_field_mapping_excel(action: cl.Action):
    """导出批量字段映射结果为 Excel 文件（聊天输入"映射"路径）"""
    user_session = cl.user_session.get("user_session")
    mapping_results = user_session.get("batch_mapping_results")
    logger.info('[ACTION] 用户点击"批量字段映射导出Excel"按钮')

    if not mapping_results:
        await cl.Message(content="❌ 未找到批量映射结果，请先执行字段映射。").send()
        return

    try:
        # 构建 Excel 数据
        excel_data = []
        for mr in mapping_results:
            rule_name = mr.get("rule_name", "批量映射")
            for m in mr.get("mappings", []):
                excel_data.append({
                    "子规则": rule_name,
                    "原始字段": m.get("原始字段名", ""),
                    "标准字段": m.get("系统属性名称", ""),
                    "匹配状态": m.get("匹配状态", ""),
                })

        # 使用 pandas 转换为 Excel
        import pandas as pd
        import io
        
        df = pd.DataFrame(excel_data)
        
        # 创建 Excel 文件内容
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='字段映射')
        
        output.seek(0)
        
        # 生成文件名
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"字段映射_批量_{date_str}.xlsx"
        
        # 发送 Excel 文件
        excel_file = cl.File(
            name=file_name,
            content=output.getvalue(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        await cl.Message(
            content=f"✅ 批量字段映射表已导出！共 {len(excel_data)} 条映射。\n\n📥 点击下载：",
            elements=[excel_file],
        ).send()
        
    except ImportError:
        logger.error("[ACTION] pandas 或 openpyxl 未安装")
        await cl.Message(content="❌ 系统缺少 Excel 导出库 (pandas/openpyxl)，请联系管理员。").send()
    except Exception as e:
        logger.error(f"[ACTION] 批量字段映射 Excel 导出异常: {e}")
        await cl.Message(content=f"❌ Excel 导出失败：{e}").send()


@cl.action_callback("reset_settings")
async def on_reset_settings(action: cl.Action):
    """用户点击"重置设置"按钮 — 恢复默认配置"""
    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"重置设置"按钮')
    
    try:
        # 重置会话状态
        user_session.current_provider = None
        user_session.model_name = None
        user_session.api_key = None
        
        # 清除运行时配置，回退到环境变量
        ModelConfig.clear_runtime_config()
        
        # 清除 Team 缓存
        from agent.core.team import reset_team_instance
        reset_team_instance()
        user_session.team = None
        
        logger.info("[ACTION] 设置已重置")
        
        # 获取默认供应商
        current_provider = ModelConfig.get_provider()
        env_api_key = ModelConfig.get_api_key()
        
        # 重置设置界面
        await cl.ChatSettings(
            [
                Select(
                    id="provider",
                    label="供应商",
                    values=["deepseek", "siliconflow"],
                    initial_index=0 if current_provider == "deepseek" else 1,
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
                    initial=env_api_key or "",
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
- 供应商：使用环境变量或默认
- API Key：使用环境变量
- Team：未初始化（配置后自动初始化）"""
        ).send()
        
    except Exception as e:
        logger.error(f"[ACTION] 重置设置失败: {e}")
        await cl.Message(content=f"❌ 重置失败：{e}").send()


def _parse_mapping_results(llm_output: str) -> list[dict] | None:
    """从 LLM 输出中解析映射结果 JSON 数组（健壮解析）。

    尝试顺序：
    1. 直接 json.loads（LLM 理想输出）
    2. 去除 markdown 代码块后再解析
    3. 正则提取 [...] JSON 数组
    """
    if not llm_output or not llm_output.strip():
        return None

    text = llm_output.strip()

    # 尝试 1: 直接解析
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # 尝试 2: 去除 markdown 代码块
    import re as _re
    code_block_match = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
    if code_block_match:
        try:
            parsed = json.loads(code_block_match.group(1).strip())
            if isinstance(parsed, list) and parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # 尝试 3: 正则提取最外层 [...] 
    bracket_match = _re.search(r"\[.*\]", text, _re.DOTALL)
    if bracket_match:
        try:
            parsed = json.loads(bracket_match.group())
            if isinstance(parsed, list) and parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def _load_object_entity_map() -> dict[str, str]:
    """从 config/对象.xlsx 加载 系统属性名称→对象 映射。"""
    try:
        from agent.tools.standard_mapper import _load_object_mapping
        import os
        excel_path = os.path.join(os.getcwd(), "config", "对象.xlsx")
        return _load_object_mapping(excel_path)
    except Exception as e:
        logger.warning(f"[MAP] 加载对象映射失败: {e}，使用默认 '事件'")
        return {}


def _render_mapping_result(
    mapping_results: list[dict], total_rule_count: int
) -> str:
    """渲染标准字段映射结果（Markdown 表格）。

    默认只展示第 1 条子规则，其余折叠提示。
    """
    lines: list[str] = []
    lines.append(f"## 📋 子规则字段映射结果（共 {total_rule_count} 条子规则）")
    lines.append("")

    for idx, mr in enumerate(mapping_results):
        rule_name = mr.get("rule_name", "未知")
        mappings = mr.get("mappings", [])
        is_first = idx == 0

        if is_first:
            lines.append(f"### 子规则 {idx + 1}：{rule_name}")
        else:
            lines.append(f"<details><summary>▶ 子规则 {idx + 1}：{rule_name}（点击展开）</summary>\n")

        lines.append("")
        lines.append("| 原始字段 | 标准字段 | 匹配状态 |")
        lines.append("|----------|---------|---------|")
        for m in mappings:
            orig = m.get("原始字段名", "")
            std = m.get("系统属性名称", "")
            status = m.get("匹配状态", "")
            status_icon = "✅" if "匹配成功" in status else "❌"
            lines.append(f"| {orig} | {std} | {status_icon} {status} |")

        # 统计
        matched = sum(1 for m in mappings if "匹配成功" in m.get("匹配状态", ""))
        total = len(mappings)
        lines.append(f"\n> 匹配率：{matched}/{total}")

        if not is_first:
            lines.append("\n</details>\n")

    lines.append("\n💡 点击上方 **📥 导出映射后子规则** 下载带标准字段映射的子规则文件。")
    return "\n".join(lines)


# ============= 日志解析辅助函数 =============

def _parse_json_safe(text: str) -> dict | None:
    """安全解析 JSON，支持 markdown 代码块包装"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re as _re2
        m = _re2.search(r"\{.*\}", text, _re2.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


def _render_log_parser_result(classification: dict | None, format_info: dict | None) -> str:
    """将 pipeline 结果渲染为用户可读的 Markdown 文本"""
    if classification is None:
        return "❌ 日志解析失败：无法解析分类结果"

    status = classification.get("status", "FAILED")
    if status == "FAILED":
        error = classification.get("error", "未知错误")
        return f"❌ 日志解析失败: {error}"

    log_format = classification.get("log_format", "未知")
    feature_field = classification.get("feature_field", "log_type")
    feature_count = classification.get("feature_count", 0)
    feature_identifier = classification.get("feature_identifier", "")
    overall_summary = classification.get("overall_summary", "")
    categorical_features = classification.get("categorical_features", "")
    diversion_method = classification.get("Diversion_method", "")
    details = classification.get("classification_details", [])

    lines: list[str] = []
    lines.append("## 🔍 日志解析结果")
    lines.append("")
    lines.append(f"| 项目 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 日志格式 | {log_format} |")
    lines.append(f"| 业务分类字段 | `{feature_field}` |")
    lines.append(f"| 特征标识符 | `{feature_identifier}` |")
    if categorical_features:
        lines.append(f"| 分类特征名称 | {categorical_features} |")
    if diversion_method:
        lines.append(f"| 分流方法 | {diversion_method} |")
    lines.append(f"| 分类数量 | {feature_count} |")

    # CHANGED: 展示 log_format_detail（LLM 原始描述），避免与上方 log_format 枚举值重复
    log_format_detail = classification.get("log_format_detail", "")
    if log_format_detail:
        lines.append(f"| 格式详情 | {log_format_detail} |")

    if overall_summary:
        lines.append("")
        lines.append(f"### 📝 综合描述")
        lines.append(overall_summary)

    if details:
        lines.append("")
        lines.append(f"### 📊 分类详情（{len(details)} 类）")
        lines.append("")
        lines.append("| 字段值 | 特征值 | 真实样例 |")
        lines.append("|---|---|---|")
        for _d in details:
            # CHANGED: 取消硬截断，完整展示字段内容
            value = str(_d.get("logtype", ""))
            # CHANGED: meaning/matched_regex 已废弃，改用 logtype + sample 展示
            feature_val = str(_d.get("logtype", ""))
            real_samples = _d.get("real_samples", [])
            if isinstance(real_samples, str):
                sample = real_samples
            elif real_samples:
                sample = real_samples[0] if isinstance(real_samples, list) else str(real_samples)
            else:
                sample = str(_d.get("sample", ""))
            lines.append(f"| {value} | {feature_val} | {sample} |")

    lines.append("")
    lines.append("*以上结果由 LogParser Pipeline 直接生成*")
    return "\n".join(lines)
