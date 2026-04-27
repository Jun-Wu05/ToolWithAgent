"""
数据映射智能助手 - Chainlit聊天界面

核心特点：
1. 对话式交互，Agent通过聊天与用户沟通
2. 支持在聊天中拖拽上传文件
3. 与Agno Team无缝集成（纯UI层）
4. 使用 cl.Dataframe 展示映射结果，支持排序/筛选/导出

使用JSON格式接收Agent的映射结果：
[{"原始字段名": "xxx", "系统属性名称": "yyy", "匹配状态": "匹配成功"}]

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY 或在.env文件
2. 运行: chainlit run web/chainlit_app.py
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

# 验证路径（使用 logger 而不是 print，避免 stdout 句柄问题）
# =========================================

# 加载.env文件
from dotenv import load_dotenv
load_dotenv()

import chainlit as cl
import json
import re
import io
from datetime import datetime

# 初始化日志
from src.logger import get_logger
logger = get_logger("chainlit_app")
logger.info("=" * 60)
logger.info("Chainlit聊天式Web应用启动")
logger.info("=" * 60)


# ============= 工具函数 =============

# 从 parsers 模块导入解析函数
from web.parsers import parse_json_mapping_result, parse_json_threat_result, create_dataframe_elements

# 从 threat_fill_handler 导入填充函数
from src.threat_fill_handler import apply_threat_mapping, export_to_base64, find_normalize_item

# 从 enum_field_tool 导入枚举填充函数（纯函数版本）
from agent.tools.enum_field_tool import (
    read_enum_mappings_from_excel,
    get_enum_preview,
    apply_enum_fill,
    export_enum_to_base64,
    apply_enum_with_base64,
)


# ============= 路由关键词库（从配置文件加载）=============

def _load_route_keywords():
    """从 config/route_keywords.json 加载路由关键词"""
    import json as _json
    _config_path = os.path.join(_project_root, "config", "route_keywords.json")
    _defaults = {
        "mapping_keywords": ["映射", "字段", "标准字段", "字段映射"],
        "threat_keywords": ["威胁类型", "threat_type", "威胁类型标准化", "威胁类型映射"],
        "enum_keywords": ["枚举", "枚举字段", "enum"],
    }
    try:
        with open(_config_path, "r", encoding="utf-8") as _f:
            _data = _json.load(_f)
        return (
            _data.get("mapping_keywords", _defaults["mapping_keywords"]),
            _data.get("threat_keywords", _defaults["threat_keywords"]),
            _data.get("enum_keywords", _defaults["enum_keywords"]),
        )
    except Exception as _e:
        logger.warning(f"[CONFIG] 加载 route_keywords.json 失败: {_e}，使用默认关键词")
        return (
            _defaults["mapping_keywords"],
            _defaults["threat_keywords"],
            _defaults["enum_keywords"],
        )

MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS = _load_route_keywords()


# ============= Chainlit 事件处理 =============

_agno_bridge_installed: bool = False


@cl.on_chat_start
async def start():
    """聊天开始时初始化"""
    # 安装 Agno 日志拦截器（仅一次）
    global _agno_bridge_installed
    if not _agno_bridge_installed:
        _setup_agno_logging_bridge()
        _agno_bridge_installed = True

    # 创建用户会话状态
    user_session = {
        "team": None,
        "decoded_data": None,
        "decoded_fields": None,
        "original_log": None,
        "last_mapping_data": None,  # 保存最后一次映射结果
        # 威胁填充模式相关
        "threat_fill_mode": False,  # 威胁填充模式标志
        "threat_target_field": None,  # 用户输入的目标字段名
        "threat_mapping_table": None,  # 威胁映射表格
        "pending_base64": None,  # 待处理的Base64内容
        # 枚举填充模式相关
        "enum_fill_mode": False,  # 枚举填充模式标志
        "enum_base64": None,  # 枚举待处理的Base64内容
        "enum_excel_path": None,  # 枚举映射表Excel路径
        "enum_preview": None,  # 枚举预览数据
    }
    cl.user_session.set("user_session", user_session)
    
    # 初始化Team并预热
    try:
        import sys, os
        _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        
        from agent.core.team import create_data_mapping_team
        user_session["team"] = create_data_mapping_team()
        logger.info("[START] Team初始化成功，开始预热...")
        
        # 执行一次空操作预热（避免首次调用延迟）
        import asyncio
        warmup_result = await asyncio.to_thread(user_session["team"].run, "你好")
        logger.info("[START] Team预热完成")
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
    
    # 处理文本消息 - 纯UI，直接传递给Team
    user_text = message.content.strip()
    if user_text:
        await handle_user_message(user_session, team, user_text)


# ============= 文件处理 =============

async def handle_file_upload(user_session: dict, element):
    """处理文件上传"""
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
        # 如果处于威胁填充模式，优先处理威胁填充逻辑
        if user_session.get("threat_fill_mode"):
            mapping_table = user_session.get("threat_mapping_table")
            
            if not mapping_table:
                await cl.Message(content="❌ 威胁映射表格丢失，请重新执行威胁类型映射").send()
                user_session["threat_fill_mode"] = False
                return
            
            # 检查是否已有目标字段名
            target_field = user_session.get("threat_target_field")
            
            if target_field:
                # 有字段名，直接执行填充
                logger.info(f"[FILE_UPLOAD] 威胁填充模式，有字段名，直接执行填充")
                await execute_threat_fill(user_session, file_content)
            else:
                # 没有字段名，保存文件内容，等待消息中的字段名
                logger.info(f"[FILE_UPLOAD] 威胁填充模式，无字段名，保存文件到 pending_base64")
                user_session["pending_base64"] = file_content
                await cl.Message(content="📁 **Base64 文件已上传！**\n\n请在下方发送目标字段名（如：original_log）来完成填充。").send()
            
            return
        # ========== 枚举填充模式状态隔离 ==========
        # 如果处于枚举填充模式，优先处理枚举填充逻辑
        if user_session.get("enum_fill_mode"):
            enum_excel_path = user_session.get("enum_excel_path")
            
            if not enum_excel_path:
                await cl.Message(content="❌ 枚举映射表路径丢失，请重新上传Excel映射表").send()
                user_session["enum_fill_mode"] = False
                return
            
            logger.info(f"[FILE_UPLOAD] 枚举填充模式，执行枚举填充")
            await execute_enum_fill(user_session, file_content)
            return
        # ========== 枚举填充模式结束 ==========
        
        # ========== 检测 Excel 枚举映射表 ==========
        # 检查是否是 Excel 文件（枚举映射表）
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
        # ========== Excel 枚举映射表检测结束 ==========
        
        # 正常模式：解码 Base64 内容
        from agent.core.agent import simple_decode
        result = simple_decode(file_content)
        
        if result["status"] == "success":
            user_session["decoded_data"] = result["decoded_json"]
            user_session["decoded_fields"] = result["fields"]
            user_session["original_log"] = result["original_log"]
            
            # 构建简化 JSON（只包含必要的索引和日志示例）
            indexes = result.get("fields", [])
            original_log = result.get("original_log", [])
            original_log_sample = original_log[0] if original_log else ""
            
            simplified_data = {
                "fields": indexes,  # 全量 index 列表
                "original_log_sample": original_log_sample
            }
            user_session["simplified_data"] = simplified_data
            
            # 记录简化 JSON
            import json as json_module
            simplified_json_str = json_module.dumps(simplified_data, ensure_ascii=False)
            logger.info(f"[DECODE] 简化JSON（发送给LLM）: {simplified_json_str[:500]}...")
            
            # 检查是否有待处理的枚举 Excel 路径（同时上传场景的反向处理）
            enum_excel_path = user_session.get("enum_excel_path")
            enum_preview = user_session.get("enum_preview")
            
            if enum_excel_path and enum_preview:
                logger.info(f"[FILE_UPLOAD] 检测到已有枚举 Excel + 新上传 Base64，执行一站式填充")
                
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


# ============= 威胁填充执行函数 =============

async def execute_threat_fill(user_session: dict, file_content: str):
    """
    执行威胁类型填充
    
    Args:
        user_session: 用户会话状态
        file_content: Base64 文件内容
    """
    logger.info("[execute_threat_fill] 开始执行威胁类型填充")
    
    target_field = user_session.get("threat_target_field")
    mapping_table = user_session.get("threat_mapping_table")
    
    logger.info(f"[execute_threat_fill] 目标字段: {target_field}, 映射数量: {len(mapping_table) if mapping_table else 0}")
    
    if not mapping_table:
        await cl.Message(content="❌ 威胁映射表格丢失，请重新执行威胁类型映射").send()
        user_session["threat_fill_mode"] = False
        return
    
    # 尝试解析 Base64 文件内容
    from agent.core.agent import simple_decode
    result = simple_decode(file_content)
    
    if result["status"] == "success":
        decoded_data = result["decoded_json"]
        logger.info("[execute_threat_fill] Base64 解码成功")
    else:
        # 如果解码失败，尝试直接使用文件内容作为 JSON
        logger.info("[execute_threat_fill] Base64解码失败，尝试直接解析")
        try:
            decoded_data = json.loads(file_content)
        except:
            await cl.Message(content=f"❌ 文件解析失败：{result.get('error_message', '未知错误')}").send()
            return
    
    # 执行威胁映射填充
    try:
        # 转换 mapping_table 格式（从 Dataframe 格式转换为 threat_fill_handler 格式）
        formatted_mapping = []
        for item in mapping_table:
            if isinstance(item, dict):
                formatted_mapping.append({
                    "mappingType": item.get("mappingType", "REGULAR"),
                    "orgValue": item.get("orgValue", ""),
                    "mappingValue": item.get("mappingValue", "")
                })
            else:
                formatted_mapping.append({
                    "mappingType": str(item.get("mappingType", "REGULAR")),
                    "orgValue": str(item.get("orgValue", "")),
                    "mappingValue": str(item.get("mappingValue", ""))
                })
        
        logger.info(f"[execute_threat_fill] 格式化映射数量: {len(formatted_mapping)}")
        
        # 应用映射
        updated_data = apply_threat_mapping(decoded_data, formatted_mapping, target_field)
        logger.info("[execute_threat_fill] 映射应用成功")
        
        # 导出 Base64
        base64_result = export_to_base64(updated_data)
        logger.info(f"[execute_threat_fill] Base64导出成功，长度: {len(base64_result)}")
        
        # 重置威胁填充模式
        user_session["threat_fill_mode"] = False
        user_session["threat_target_field"] = None
        user_session["threat_mapping_table"] = None
        user_session["pending_base64"] = None
        
        # 发送成功消息
        await cl.Message(
            content=f"""✅ **威胁类型填充完成！**

📊 **填充统计：**
- 目标字段：{target_field}
- 映射数量：{len(formatted_mapping)} 条

💾 点击下方按钮下载填充后的配置文件。"""
        ).send()
        
        # 发送可下载的 Base64 文件
        base64_file = cl.File(
            name="threat_filled_config.txt",
            content=base64_result.encode('utf-8'),
            mime="text/plain",
        )
        
        await cl.Message(
            content="**📥 点击下载填充后的配置：**",
            elements=[base64_file]
        ).send()
        
    except ValueError as e:
        logger.error(f"[execute_threat_fill] 填充失败: {e}")
        await cl.Message(content=f"❌ 填充失败：{str(e)}").send()
    except Exception as e:
        logger.error(f"[execute_threat_fill] 填充异常: {str(e)}")
        import traceback
        logger.error(f"[execute_threat_fill] 详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 填充异常：{str(e)}").send()


# ============= 枚举填充执行函数 =============

async def execute_enum_fill(user_session: dict, file_content: str):
    """
    执行枚举字段填充
    
    Args:
        user_session: 用户会话状态
        file_content: Base64 文件内容
    """
    logger.info("[execute_enum_fill] 开始执行枚举填充")
    
    enum_excel_path = user_session.get("enum_excel_path")
    enum_preview = user_session.get("enum_preview")
    
    logger.info(f"[execute_enum_fill] Excel路径: {enum_excel_path}")
    
    if not enum_excel_path:
        await cl.Message(content="❌ 枚举映射表路径丢失，请重新上传Excel映射表").send()
        user_session["enum_fill_mode"] = False
        return
    
    # 尝试解析 Base64 文件内容
    from agent.core.agent import simple_decode
    result = simple_decode(file_content)
    
    if result["status"] == "success":
        decoded_data = result["decoded_json"]
        logger.info("[execute_enum_fill] Base64 解码成功")
    else:
        # 如果解码失败，尝试直接使用文件内容作为 JSON
        logger.info("[execute_enum_fill] Base64解码失败，尝试直接解析")
        try:
            decoded_data = json.loads(file_content)
        except:
            await cl.Message(content=f"❌ 文件解析失败：{result.get('error_message', '未知错误')}").send()
            return
    
    # 执行枚举填充
    try:
        # 应用枚举填充
        updated_data = apply_enum_fill(decoded_data, enum_excel_path)
        logger.info("[execute_enum_fill] 枚举填充应用成功")
        
        # 导出 Base64
        base64_result = export_enum_to_base64(updated_data)
        logger.info(f"[execute_enum_fill] Base64导出成功，长度: {len(base64_result)}")
        
        # 重置枚举填充模式
        user_session["enum_fill_mode"] = False
        user_session["enum_excel_path"] = None
        user_session["enum_preview"] = None
        
        # 计算填充统计
        field_count = len(enum_preview) if enum_preview else 0
        
        # 发送成功消息
        await cl.Message(
            content=f"""✅ **枚举字段填充完成！**

📊 **填充统计：**
- 映射表：{enum_excel_path}
- 映射数量：{field_count} 条

💾 点击下方按钮下载填充后的配置文件。"""
        ).send()
        
        # 发送可下载的 Base64 文件
        base64_file = cl.File(
            name="enum_filled_config.txt",
            content=base64_result.encode('utf-8'),
            mime="text/plain",
        )
        
        await cl.Message(
            content="**📥 点击下载填充后的配置：**",
            elements=[base64_file]
        ).send()
        
    except FileNotFoundError as e:
        logger.error(f"[execute_enum_fill] 文件未找到: {e}")
        await cl.Message(content=f"❌ Excel 文件未找到：{str(e)}").send()
    except ValueError as e:
        logger.error(f"[execute_enum_fill] 填充失败: {e}")
        await cl.Message(content=f"❌ 填充失败：{str(e)}").send()
    except Exception as e:
        logger.error(f"[execute_enum_fill] 填充异常: {str(e)}")
        import traceback
        logger.error(f"[execute_enum_fill] 详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 填充异常：{str(e)}").send()


async def _handle_enum_fill_flow(user_session: dict, user_text: str) -> bool:
    """
    枚举填充模式专属流程

    Returns:
        True 表示已处理（调用方应直接 return），False 表示未命中枚举填充模式
    """
    if not user_session.get("enum_fill_mode"):
        return False

    logger.info(f"[HANDLE] 枚举填充模式，检查用户输入: {user_text}")

    enum_excel_path = user_session.get("enum_excel_path")
    if not enum_excel_path:
        await cl.Message(content="❌ 枚举映射表路径丢失，请重新上传Excel映射表").send()
        user_session["enum_fill_mode"] = False
        return True

    # 枚举模式需要用户上传 Base64 文件
    logger.info("[HANDLE] 枚举模式，等待用户上传Base64文件")
    await cl.Message(
        content=f"""📋 **枚举填充模式已开启**

已选择映射表：{enum_excel_path}

请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"""
    ).send()
    return True


# ============= Action 回调处理 =============

@cl.action_callback("fill_threat_with_field")
async def on_fill_threat_with_field(action: cl.Action):
    """处理威胁类型带字段填充按钮点击"""
    logger.info("[fill_threat_with_field] 收到带字段填充回调")
    user_session = cl.user_session.get("user_session")
    
    # 获取威胁映射结果
    threat_data = user_session.get("last_threat_data")
    
    if not threat_data:
        logger.warning("[fill_threat_with_field] 没有威胁映射结果")
        await cl.Message(content="❌ 没有可用的威胁映射结果，请先执行威胁类型映射").send()
        return
    
    # 保存映射表格到会话
    user_session["threat_mapping_table"] = threat_data
    
    # 设置威胁填充模式
    user_session["threat_fill_mode"] = True
    user_session["threat_target_field"] = None
    logger.info(f"[fill_threat_with_field] 开启威胁填充模式，保存映射表格 {len(threat_data)} 条")
    
    # 发送提示消息
    await cl.Message(
        content="""📥 **威胁类型填充模式已开启**

请输入**目标字段名**（如：original_log）

输入字段名后，系统会等待您上传 Base64 配置文件，然后执行填充。"""
    ).send()


@cl.action_callback("confirm_fill")
async def on_confirm_fill(action: cl.Action):
    """处理确认填充按钮点击"""
    logger.info("[confirm_fill] 收到确认填充回调")
    user_session = cl.user_session.get("user_session")
    
    # 获取映射结果和原始数据
    mapping_data = user_session.get("last_mapping_data")
    decoded_data = user_session.get("decoded_data")
    
    logger.info(f"[confirm_fill] mapping_data: {type(mapping_data)}, 长度: {len(mapping_data) if mapping_data else 0}")
    logger.info(f"[confirm_fill] decoded_data: {type(decoded_data)}, 是否有数据: {bool(decoded_data)}")
    
    if not mapping_data:
        logger.warning("[confirm_fill] 没有映射结果")
        await cl.Message(content="❌ 没有可用的映射结果，请先执行字段映射").send()
        return
    
    if not decoded_data:
        logger.warning("[confirm_fill] 没有原始数据")
        await cl.Message(content="❌ 没有可用的原始数据，请先上传文件").send()
        return
    
    await cl.Message(content="⏳ **正在执行填充操作...**").send()
    
    try:
        # 导入字段映射处理器
        from src.field_mapping_handler import get_field_mapping_handler
        
        handler = get_field_mapping_handler()
        
        # 应用字段映射
        logger.info("[confirm_fill] 开始应用字段映射")
        updated_config, updated_count = handler.apply_field_mapping(decoded_data, mapping_data)
        logger.info(f"[confirm_fill] 字段映射完成，更新数量: {updated_count}")
        
        if updated_count == 0:
            await cl.Message(content="⚠️ 没有找到需要更新的字段").send()
            return
        
        # 导出为 Base64
        logger.info("[confirm_fill] 开始导出Base64")
        base64_result = handler.export_to_base64(updated_config)
        logger.info(f"[confirm_fill] Base64导出完成，长度: {len(base64_result)}")
        
        # 保存更新后的配置
        user_session["updated_config"] = updated_config
        
        # 发送成功消息
        success_msg = f"""✅ **填充完成！**

📊 **更新统计：**
- 更新字段数：{updated_count} 个

💾 **输出选项：**
- 点击下方按钮下载 Base64 编码结果"""
        logger.info(f"[confirm_fill] 发送成功消息: {success_msg[:50]}...")
        await cl.Message(content=success_msg).send()
        
        # 发送可下载的 Base64 文件
        file_content = base64_result.encode('utf-8')
        logger.info(f"[confirm_fill] 创建File元素, 大小: {len(file_content)} bytes")
        
        base64_file = cl.File(
            name="filled_config.txt",
            content=file_content,
            mime="text/plain",
        )
        
        logger.info("[confirm_fill] 发送文件消息")
        await cl.Message(
            content="**📥 点击下载填充后的配置：**",
            elements=[base64_file]
        ).send()
        
        logger.info("[confirm_fill] 完成")
        
    except Exception as e:
        logger.error(f"填充操作异常: {str(e)}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 填充失败：{str(e)}").send()


@cl.action_callback("start_enum_fill")
async def on_start_enum_fill(action: cl.Action):
    """处理开始枚举填充按钮点击"""
    logger.info("[start_enum_fill] 收到开始枚举填充回调")
    user_session = cl.user_session.get("user_session")
    
    # 获取枚举预览数据
    enum_preview = user_session.get("enum_preview")
    
    if not enum_preview:
        logger.warning("[start_enum_fill] 没有枚举预览数据")
        await cl.Message(content="❌ 没有可用的枚举映射表预览，请先上传Excel映射表").send()
        return
    
    # 设置枚举填充模式
    user_session["enum_fill_mode"] = True
    logger.info(f"[start_enum_fill] 开启枚举填充模式，预览数量: {len(enum_preview)}")
    
    # 发送提示消息
    await cl.Message(
        content="""📥 **枚举填充模式已开启**

请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"""
    ).send()


# ============= 用户消息处理（子函数）=============

def _route_request(user_lower: str, user_text: str):
    """
    硬路由匹配：根据关键词判断请求类型并添加前缀标签

    Returns:
        (routed_text: str, is_mapping: bool, is_threat: bool, is_enum: bool)
    """
    is_mapping = False
    is_threat = False
    is_enum = False

    if any(kw in user_lower for kw in THREAT_KEYWORDS):
        logger.info("[HARD_ROUTE] 命中威胁类型关键词")
        user_text = f"[威胁类型] {user_text}"
        is_threat = True
    elif any(kw in user_lower for kw in ENUM_KEYWORDS):
        logger.info("[HARD_ROUTE] 命中枚举关键词")
        user_text = f"[枚举处理] {user_text}"
        is_enum = True
    elif any(kw in user_lower for kw in MAPPING_KEYWORDS):
        logger.info("[HARD_ROUTE] 命中字段映射关键词")
        user_text = f"[字段映射] {user_text}"
        is_mapping = True

    return user_text, is_mapping, is_threat, is_enum


def _build_llm_input(user_text: str, user_session: dict, is_mapping: bool) -> str:
    """
    构建发送给 LLM / Team 的完整输入

    - 字段映射请求：拼接字段列表 JSON + 原始日志样本
    - 威胁类型 / 枚举 / 无数据请求：仅传用户原始文本
    """
    has_data = user_session.get("decoded_data") or user_session.get("decoded_fields")

    if has_data and is_mapping:
        simplified_data = user_session.get("simplified_data", {})
        fields_list = simplified_data.get("fields", [])
        original_log_sample = simplified_data.get("original_log_sample", "")

        fields_json_str = json.dumps(fields_list, ensure_ascii=False)

        full_input = f"""用户请求：{user_text}

⚠️ 需要映射的字段列表（严格只处理以下字段，每个字段名必须精确匹配，不得增减任何字段）：
{fields_json_str}

请根据以上字段列表进行标准字段映射处理。"""

        if original_log_sample:
            sample_str = original_log_sample if len(original_log_sample) <= 2000 else original_log_sample[:2000] + "...(已截断)"
            full_input += f"""

---
📋 原始日志样本（仅用于理解字段语义，字段列表以上方 JSON 数组为准）：
{sample_str}"""

        logger.info(f"[LLM_INPUT] 发送给LLM的字段列表: {fields_json_str[:500]}...")
    else:
        full_input = user_text

    return full_input


async def _handle_threat_fill_flow(user_session: dict, user_text: str) -> bool:
    """
    威胁填充模式专属流程

    Returns:
        True 表示已处理（调用方应直接 return），False 表示未命中威胁填充模式
    """
    if not user_session.get("threat_fill_mode"):
        return False

    logger.info(f"[HANDLE] 威胁填充模式，检查用户输入: {user_text}")

    mapping_table = user_session.get("threat_mapping_table")
    if not mapping_table:
        await cl.Message(content="❌ 威胁映射表格丢失，请重新执行威胁类型映射").send()
        user_session["threat_fill_mode"] = False
        return True

    target_field = user_text.strip()

    pending_base64 = user_session.get("pending_base64")
    if pending_base64 and not user_session.get("threat_target_field"):
        user_session["threat_target_field"] = target_field
        logger.info(f"[HANDLE] 已记录目标字段: {target_field}，有 pending_base64，执行填充")
        await execute_threat_fill(user_session, pending_base64)
        return True

    if not user_session.get("threat_target_field"):
        user_session["threat_target_field"] = target_field
        logger.info(f"[HANDLE] 已记录目标字段: {target_field}，等待文件上传")
        await cl.Message(
            content=f"""✅ **目标字段已记录：{target_field}**

请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"""
        ).send()
        return True

    logger.info("[HANDLE] 等待用户上传Base64文件")
    await cl.Message(
        content=f"📋 当前状态：\n- 目标字段：{user_session.get('threat_target_field')}\n- 映射数量：{len(mapping_table)} 条\n\n请上传 Base64 配置文件"
    ).send()
    return True


async def _call_team_with_retry(team, full_input: str, loading_msg) -> object:
    """
    调用 Team.run，带指数退避重试（最多 3 次）

    Returns:
        Team.run 的返回结果
    """
    import asyncio as asyncio_mod
    import time

    last_exception = None
    for attempt in range(1, 4):
        try:
            api_start_time = time.time()
            logger.info(f"[API] 开始调用 Team.run (尝试 {attempt}/3)，输入长度: {len(full_input)}")

            result = await asyncio_mod.to_thread(team.run, full_input)

            api_duration = time.time() - api_start_time
            logger.info(f"[API] Team.run 完成，耗时: {api_duration:.2f}秒")

            # 记录 LLM 输出
            result_content = result.content if hasattr(result, 'content') else str(result)
            logger.info(f"[API] LLM输出长度: {len(result_content)} 字符")

            # 记录 Token 用量
            _log_token_usage(result)
            return result

        except Exception as e:
            last_exception = e
            if attempt < 3:
                wait_sec = 2 ** (attempt - 1)
                logger.warning(f"[API] Team.run 失败 (尝试 {attempt}/3): {e}，{wait_sec}秒后重试...")
                await asyncio_mod.sleep(wait_sec)
            else:
                logger.error(f"[API] Team.run 3次尝试全部失败: {e}")

    raise last_exception


def _log_token_usage(result):
    """记录 LLM Token 用量（深度探测 RunResponse 上所有可能存放 token/metrics 的属性）"""
    try:
        from agent.core.model_config import ModelConfig
        model_name = ModelConfig.MAIN_MODEL

        # ---- 格式化的 token 日志（单行）----
        def _emit(label: str, input_tokens, output_tokens, total_tokens, cached_tokens=None, extra_info: str = ""):
            parts = [
                f"模型: {model_name}",
                f"Tokens - 输入: {input_tokens}, 输出: {output_tokens}, 总计: {total_tokens}",
            ]
            if cached_tokens is not None:
                parts.append(f"缓存: {cached_tokens}")
            if extra_info:
                parts.append(extra_info)
            logger.info(f"[API] {label}，" + "，".join(parts))

        found_any = False

        # 1) result.usage（最常见）
        usage = getattr(result, 'usage', None)
        if usage:
            inp = getattr(usage, 'input_tokens', None) or getattr(usage, 'prompt_tokens', None)
            out = getattr(usage, 'output_tokens', None) or getattr(usage, 'completion_tokens', None)
            total = getattr(usage, 'total_tokens', None)
            cached = getattr(usage, 'cached_tokens', None)
            if inp is not None or out is not None:
                _emit("主调用", inp, out, total, cached)
                found_any = True

        # 2) result.metrics（Agno v1 可能放这里）
        metrics = getattr(result, 'metrics', None)
        if metrics is not None:
            if isinstance(metrics, dict):
                _inp = metrics.get('input_tokens') or metrics.get('prompt_tokens')
                _out = metrics.get('output_tokens') or metrics.get('completion_tokens')
                _tot = metrics.get('total_tokens')
                _cache = metrics.get('cached_tokens')
                if _inp is not None or _out is not None:
                    _emit("主调用(metrics)", _inp, _out, _tot, _cache)
                    found_any = True
            elif hasattr(metrics, 'input_tokens') or hasattr(metrics, 'total_tokens'):
                # RunMetrics 对象 - 直接提取关键字段，不逐个属性记录
                _inp = getattr(metrics, 'input_tokens', None)
                _out = getattr(metrics, 'output_tokens', None)
                _tot = getattr(metrics, 'total_tokens', None)
                _dur = getattr(metrics, 'duration', None)
                _extra = f"耗时: {_dur:.1f}s" if _dur is not None else ""
                if _inp is not None or _out is not None:
                    _emit("主调用(metrics)", _inp, _out, _tot, None, _extra)
                    found_any = True

        # 3) result.run_data / result.extra（Agno 有时会把 member-agent 的 metrics 放在这里）
        for attr_name in ('run_data', 'extra', 'run_response'):
            container = getattr(result, attr_name, None)
            if container is None:
                continue
            if isinstance(container, dict):
                for key, val in container.items():
                    _probe_nested(key, val, model_name, _emit)
                    found_any = True
            elif hasattr(container, '__dict__'):
                for key, val in container.__dict__.items():
                    if 'token' in key.lower() or 'usage' in key.lower() or 'metric' in key.lower():
                        logger.info(f"[API] {attr_name}.{key}: {val}")
                        found_any = True

        # 4) result.members / result.member_responses（Team Route 模式下子 agent 的响应）
        for attr_name in ('members', 'member_responses'):
            val = getattr(result, attr_name, None)
            if val is None:
                continue
            if isinstance(val, list):
                for idx, item in enumerate(val):
                    _probe_nested(f"Member[{idx}]", item, model_name, _emit)
                    found_any = True
            elif isinstance(val, dict):
                for key, item in val.items():
                    _probe_nested(f"Member[{key}]", item, model_name, _emit)
                    found_any = True

        # 5) 对 result 自身的 __dict__ 做通用扫描（已优化：只记录关键信息，不逐个属性输出）
        # 注意：如果需要更详细的调试信息，可以取消下面注释
        # if hasattr(result, '__dict__'):
        #     for key, val in result.__dict__.items():
        #         if key.startswith('_'):
        #             continue
        #         if any(kw in key.lower() for kw in ('usage', 'token', 'metric', 'response', 'run')):
        #             if isinstance(val, (dict, list)):
        #                 _probe_nested(key, val, model_name, _emit)
        #                 found_any = True
        #             elif not isinstance(val, str) and hasattr(val, '__dict__'):
        #                 _probe_nested(key, val, model_name, _emit)
        #                 found_any = True

        if not found_any:
            logger.info(f"[API] 模型: {model_name}，Token 用量未获取到（RunResponse 上无 usage/metrics 属性，请依赖 Agno logging bridge）")
    except Exception:
        pass  # Token 记录失败不影响主流程


def _probe_nested(label: str, obj, model_name: str, emit_fn):
    """递归探测嵌套对象上的 token 信息"""
    if obj is None:
        return
    if isinstance(obj, dict):
        inp = obj.get('input_tokens') or obj.get('prompt_tokens')
        out = obj.get('output_tokens') or obj.get('completion_tokens')
        total = obj.get('total_tokens')
        cached = obj.get('cached_tokens')
        if inp is not None or out is not None:
            emit_fn(label, inp, out, total, cached)
        # 子字典
        for k, v in obj.items():
            if k in ('usage', 'metrics', 'response', 'run_response') and isinstance(v, dict):
                _probe_nested(f"{label}/{k}", v, model_name, emit_fn)
    elif hasattr(obj, '__dict__'):
        usage = getattr(obj, 'usage', None)
        if usage is not None:
            inp = getattr(usage, 'input_tokens', None) or getattr(usage, 'prompt_tokens', None)
            out = getattr(usage, 'output_tokens', None) or getattr(usage, 'completion_tokens', None)
            total = getattr(usage, 'total_tokens', None)
            cached = getattr(usage, 'cached_tokens', None)
            if inp is not None or out is not None:
                emit_fn(label, inp, out, total, cached)
        metrics = getattr(obj, 'metrics', None)
        if metrics is not None and isinstance(metrics, dict):
            _probe_nested(f"{label}/metrics", metrics, model_name, emit_fn)


def _setup_agno_logging_bridge():
    """
    拦截 Agno 框架内部的 DEBUG/INFO logger，提取 Token 用量信息。

    Agno 在 debug_mode=True 时会通过 `agno` / `agno.agent` 等 logger
    输出如下格式的日志：
        DEBUG * Tokens: input=20707, output=1419, total=22126, cached=20224
        DEBUG * Duration: 63.9110s

    本函数给 logging 根节点挂一个 handler，识别这些行并转成应用级 INFO 日志。
    """
    import logging as _logging
    import re as _re

    # 预编译正则
    _TOKEN_RE = _re.compile(
        r'Tokens:\s*input=(?P<input>\d+),\s*output=(?P<output>\d+),\s*total=(?P<total>\d+)(?:,\s*cached=(?P<cached>\d+))?'
    )
    _DURATION_RE = _re.compile(r'Duration:\s*(?P<duration>[\d.]+)s')

    # 用一个闭包记录最近的 member 名称（Agno 日志中可能包含 agent name）
    # 同时用一个栈来跟踪当前正在执行的 agent
    
    # 二次保险：确保项目根目录在sys.path中
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_current_dir)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    
    from agent.core.model_config import ModelConfig
    model_name = ModelConfig.MAIN_MODEL

    class _AgnoTokenHandler(_logging.Handler):
        """捕获 agno.* logger 的 token 信息并写入应用日志"""

        def __init__(self):
            super().__init__(level=_logging.DEBUG)
            self._last_duration_s: float | None = None
            self._last_member_name: str = ""
            # 用于跟踪 member agent 名称（从日志行提取）
            self._name_pattern = _re.compile(r'\[(\w+Agent)\]|Member:\s*(\w+)')

        def emit(self, record: _logging.LogRecord):
            msg = str(record.msg) if record.msg else ""
            args = record.args if record.args else ()

            # 尝试格式化消息（处理 %s 占位符）
            try:
                if args:
                    msg = msg % args
            except Exception:
                pass

            # 1) 提取 member agent 名称
            name_match = self._name_pattern.search(msg)
            if name_match:
                self._last_member_name = name_match.group(1) or name_match.group(2) or ""

            # 2) 提取 Duration
            dur_match = _DURATION_RE.search(msg)
            if dur_match:
                self._last_duration_s = float(dur_match.group('duration'))

            # 3) 提取 Tokens
            token_match = _TOKEN_RE.search(msg)
            if not token_match:
                return  # 不是 token 日志，忽略

            input_t = token_match.group('input')
            output_t = token_match.group('output')
            total_t = token_match.group('total')
            cached_t = token_match.group('cached')

            # 确定 label
            if self._last_member_name:
                label = f"MemberAgent({self._last_member_name})"
            else:
                label = "Team Leader 路由"

            parts = [
                f"模型: {model_name}",
                f"Tokens - 输入: {input_t}, 输出: {output_t}, 总计: {total_t}",
            ]
            if cached_t:
                parts.append(f"缓存: {cached_t}")
            if self._last_duration_s is not None:
                parts.append(f"耗时: {self._last_duration_s:.1f}s")
                self._last_duration_s = None  # 只用一次，避免跨调用污染

            logger.info(f"[API] {label}，" + "，".join(parts))

    # ---- 安装 handler ----
    handler = _AgnoTokenHandler()

    # 拦截 agno 相关的 logger（覆盖 agno、agno.agent、agno.team 等）
    for name in ('agno', 'agno.agent', 'agno.team', 'agno.models', ''):
        logger_obj = _logging.getLogger(name)
        logger_obj.addHandler(handler)
        logger_obj.setLevel(_logging.DEBUG)

    logger.info("[LOGGING_BRIDGE] Agno 日志拦截器已安装，将捕获 Token 用量信息")

    return handler  # 返回 handler 引用，防止被 GC


async def _process_team_response(
    result,
    user_lower: str,
    user_session: dict,
    loading_msg,
    msg
) -> bool:
    """
    解析 Team 返回结果：识别映射/威胁类型并渲染表格，或流式输出原文

    Returns:
        True 表示已处理为表格（调用方可 return），False 表示需要继续流式输出
    """
    result_content = result.content if hasattr(result, 'content') else str(result)

    is_mapping_request = any(keyword in user_lower for keyword in ["映射", "字段", "map"])
    is_threat_request = any(keyword in user_lower for keyword in ["威胁", "threat"])

    logger.info(f"[HANDLE] is_mapping_request: {is_mapping_request}, is_threat_request: {is_threat_request}")

    # 字段映射结果处理
    if is_mapping_request:
        mapping_data = parse_json_mapping_result(result_content)
        if mapping_data:
            user_session["last_mapping_data"] = mapping_data
            matched_count = sum(1 for item in mapping_data if item.get("匹配状态") == "匹配成功")
            unmatched_count = len(mapping_data) - matched_count

            summary = f"""✅ **字段映射完成！**

📊 **映射统计：**
- 总字段数：{len(mapping_data)}
- 匹配成功：{matched_count} 个
- 未匹配：{unmatched_count} 个

✨ **表格功能：**
- 📌 点击列标题排序
- 🔍 使用搜索框筛选
- ✏️ 点击单元格编辑系统属性名称
- 📥 导出CSV文件"""

            for i in range(0, len(summary), 50):
                await msg.stream_token(summary[i:i+50])
            await msg.update()

            elements = create_dataframe_elements(mapping_data)
            if elements:
                await cl.Message(
                    content="**📋 字段映射表：**\n\n请确认映射结果，点击下方按钮填充到原始数据中。",
                    elements=elements,
                    actions=[
                        cl.Action(name="confirm_fill", label="✅ 确认填充", description="确认后将映射结果填充到原始数据", payload={})
                    ]
                ).send()
            return True

    # 威胁类型结果处理
    if is_threat_request:
        logger.info("[HANDLE] 进入威胁类型处理分支")
        threat_data = parse_json_threat_result(result_content)
        logger.info(f"[HANDLE] threat_data解析结果: {type(threat_data)}, 长度: {len(threat_data) if threat_data else 0}")

        if threat_data:
            user_session["last_threat_data"] = threat_data
            threat_count = len(threat_data)

            summary = f"""✅ **威胁类型映射完成！**

📊 **映射统计：**
- 映射数量：{threat_count} 条

✨ **表格功能：**
- 📌 点击列标题排序
- 🔍 使用搜索框筛选
- 📥 导出CSV文件"""

            for i in range(0, len(summary), 50):
                await msg.stream_token(summary[i:i+50])
            await msg.update()

            elements = create_dataframe_elements(threat_data)
            if elements:
                await cl.Message(
                    content="**📋 威胁类型映射表：**\n\n请先输入目标字段名并上传Base64文件，然后点击下方按钮进行填充。",
                    elements=elements,
                    actions=[
                        cl.Action(name="fill_threat_with_field", label="📥 带字段填充", description="输入目标字段并上传Base64文件进行填充", payload={})
                    ]
                ).send()
            return True

    # 流式输出原文
    for i in range(0, len(result_content), 50):
        await msg.stream_token(result_content[i:i+50])
    await msg.update()
    return True


# ============= 用户消息处理（主编排）=============

async def handle_user_message(user_session: dict, team, user_text: str):
    """处理用户消息 - 主编排函数，将工作拆分为子函数"""
    import asyncio as asyncio_mod
    import time

    user_lower = user_text.lower()

    # 1. 硬路由
    user_text, is_mapping, is_threat, is_enum = _route_request(user_lower, user_text)

    # 2. 威胁填充模式分流
    if await _handle_threat_fill_flow(user_session, user_text):
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

    # 4. 构建 LLM 输入
    full_input = _build_llm_input(user_text, user_session, is_mapping)

    # 5. 发送 loading 消息
    loading_msg = cl.Message(content="⏳ **AI正在处理中，请稍候...**\n\n💭 正在分析您的请求...")
    await loading_msg.send()

    try:
        # 6. 调用 Team（带重试）
        result = await _call_team_with_retry(team, full_input, loading_msg)

        # 7. 删除 loading 消息
        await loading_msg.remove()

        # 8. 创建流式消息显示结果
        msg = cl.Message(content="")
        await msg.send()

        # 9. 解析响应
        await _process_team_response(result, user_lower, user_session, loading_msg, msg)

    except Exception as e:
        logger.error(f"Team调用异常: {str(e)}")
        try:
            await loading_msg.remove()
        except Exception:
            pass
        await cl.Message(content=f"❌ 处理异常：{str(e)}").send()


async def send_action_buttons(msg, mapping_data: list):
    """发送操作按钮消息"""
    import pandas as pd
    
    # 创建Excel文件
    df = pd.DataFrame(mapping_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='字段映射表', index=False)
    excel_data = output.getvalue()
    
    # 创建CSV文件
    csv_content = df.to_csv(index=False, encoding='utf-8-sig')
    csv_bytes = csv_content.encode('utf-8-sig')
    
    # 保存到会话中供下载
    user_session = cl.user_session.get("user_session")
    user_session["excel_data"] = excel_data
    user_session["excel_filename"] = f"字段映射表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    # 发送Excel下载按钮
    excel_file = cl.File(
        name=user_session["excel_filename"],
        content=excel_data,
    )
    
    # 发送JSON复制内容
    json_str = json.dumps(mapping_data, ensure_ascii=False, indent=2)
    json_file = cl.File(
        name="映射结果.json",
        content=json_str.encode('utf-8'),
    )
    
    # 发送操作提示和下载元素
    action_msg = cl.Message(
        content="""
---

**📋 操作选项：**

- 📥 **下载 Excel** - 导出映射表为Excel文件
- 📋 **下载 JSON** - 复制映射结果为JSON格式
- 🔢 **复制内容** - 直接复制下方JSON字符串
""",
        elements=[excel_file, json_file]
    )
    await action_msg.send()
    
    # 发送可复制的JSON内容
    json_msg = cl.Message(
        content=f"```json\n{json_str}\n```"
    )
    await json_msg.send()
