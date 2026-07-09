"""
Chainlit 文件上传处理器 - 从 chainlit_app.py 提取

本模块处理所有文件上传场景：
- 威胁填充模式
- 枚举填充模式
- Excel 枚举映射表检测
- Excel 数据表格解析
- Base64 / TXT 解码
"""

import chainlit as cl
import json
from datetime import datetime
from typing import Set
from agent.shared.logger import get_logger

logger = get_logger("upload_handlers")

# 从拆分模块导入业务函数
from web.file_handler import (
    read_element_content,
    decode_file_content,
    build_simplified_data,
    get_element_file_name,
)
from web.threat_handler import execute_threat_fill
from web.enum_handler import execute_enum_fill
from agent.tools.enum_field_tool import get_enum_preview
from web.parsers import create_dataframe_elements


# 枚举映射表列头关键词（从 utils 导入）
try:
    from web.utils import _ENUM_HEADER_KEYWORDS
except ImportError:
    # 向后兼容：如果 utils.py 还没有导出，使用本地定义
    _ENUM_HEADER_KEYWORDS: Set[str] = {
        "mappingtype", "orgvalue", "mappingvalue",
        "原始值", "映射值", "映射类型",
        "目标字段", "target_field", "targetfield"
    }


async def handle_file_upload(user_session, element):
    """
    处理文件上传 — 委托给各 handler
    
    职责：
    1. 检测威胁/枚举填充模式并分流
    2. 检测 Excel 枚举映射表 vs 数据表格
    3. 解码 Base64/TXT 内容
    4. 更新会话状态
    
    Args:
        user_session: 用户会话状态（SessionState 实例或 dict）
        element: Chainlit 上传的文件元素
    """
    try:
        # 获取文件内容（委托 file_handler）
        file_content = read_element_content(element)

        # ========== 威胁填充模式状态隔离 ==========
        if user_session.get("threat_fill_mode", False):
            mapping_table = user_session.get("threat_mapping_table")

            if not mapping_table:
                await cl.Message(content="❌ 威胁映射表格丢失，请重新执行威胁类型映射").send()
                user_session["threat_fill_mode"] = False
                return

            # 检查是否已有目标字段名
            target_field = user_session.get("threat_target_field")

            if target_field:
                logger.info("[FILE_UPLOAD] 威胁填充模式，有字段名，直接执行填充")
                await execute_threat_fill(user_session, file_content)
            else:
                logger.info("[FILE_UPLOAD] 威胁填充模式，无字段名，保存文件到 pending_base64")
                user_session["pending_base64"] = file_content
                await cl.Message(
                    content="📁 **Base64 文件已上传！**\n\n请在下方发送目标字段名（如：original_log）来完成填充。"
                ).send()

            return

        # ========== 枚举填充模式状态隔离 ==========
        if user_session.get("enum_fill_mode", False):
            enum_excel_path = user_session.get("enum_excel_path")

            if not enum_excel_path:
                await cl.Message(content="❌ 枚举映射表路径丢失，请重新上传Excel映射表").send()
                user_session["enum_fill_mode"] = False
                return

            logger.info("[FILE_UPLOAD] 枚举填充模式，执行枚举填充")
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
                is_enum_table = is_enum_mapping_excel(excel_path)
                logger.info(f"[FILE_UPLOAD] Excel 表头检测: is_enum_table={is_enum_table}, file={file_name}")

                if not is_enum_table:
                    # 不是枚举映射表 → 直接读取为数据表格，供 LogParserAgent 等下游使用
                    logger.info(f"[FILE_UPLOAD] Excel 列头不匹配枚举映射表，按数据表格处理: {file_name}")
                    await _handle_excel_data_table(excel_path, file_name, user_session)
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
                            cl.Action(
                                name="start_enum_fill",
                                label="✅ 开始枚举填充",
                                description="上传 Base64 配置文件执行枚举填充",
                                payload={}
                            )
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
            # 保存解码数据（SessionState dict 兼容层支持 [] 赋值）
            user_session["decoded_data"] = result["decoded_json"]
            user_session["decoded_fields"] = result["fields"]
            user_session["original_log"] = result["original_log"]
            user_session["decoded_text"] = result.get("decoded_text", "")

            # 记录上传文件元信息
            file_name_val = get_element_file_name(element)
            file_time = datetime.now().strftime("%H:%M:%S")
            user_session["uploaded_file_name"] = file_name_val
            user_session["uploaded_file_time"] = file_time
            logger.info(f"[FILE_UPLOAD] 记录上传文件元信息: name={file_name_val}, time={file_time}")

            # 构建 simplified_data（委托 file_handler）
            user_session["simplified_data"] = build_simplified_data(result)

            # 缓存原始 Base64 内容，供枚举填充等后续操作使用
            user_session["raw_base64"] = file_content

            # 检查是否有待处理的枚举 Excel 路径（同时上传场景的反向处理）
            enum_excel_path = user_session.get("enum_excel_path")

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


def is_enum_mapping_excel(excel_path: str) -> bool:
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


async def _handle_excel_data_table(excel_path: str, file_name: str, user_session):
    """
    处理 Excel 数据表格（非枚举映射表）
    
    Args:
        excel_path: Excel 文件路径
        file_name: 文件名
        user_session: 用户会话状态
    """
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
        
        # 保存到会话（SessionState dict 兼容层支持 [] 赋值）
        user_session["original_log"] = original_log
        user_session["decoded_data"] = records
        user_session["decoded_fields"] = fields
        user_session["decoded_text"] = decoded_text
        user_session["simplified_data"] = {
            "fields": fields,
            "original_log_sample": decoded_text[:2000]
        }
        file_time = datetime.now().strftime("%H:%M:%S")
        user_session["uploaded_file_name"] = file_name
        user_session["uploaded_file_time"] = file_time

        # 保存路径供枚举填充等后续使用
        user_session["enum_excel_path"] = excel_path
        
        # 检测"原始日志"列并预提取，供 LogParserAgent 精简输入使用
        # CHANGED: 替换单元格内的换行符为空格，防止单条日志被拆散成多行碎片
        raw_log_lines = None
        for col in df.columns:
            if "原始日志" in str(col):
                raw_series = df[col].dropna().astype(str)
                # 统计并替换单元格内的 \n
                # CHANGED: 同时替换 \r 和 \n（Windows 换行 \r\n 合并为一个空格）
                newline_count = int(raw_series.str.contains(r'[\r\n]', regex=True).sum())
                if newline_count > 0:
                    raw_log_lines = raw_series.str.replace(r'[\r\n]+', ' ', regex=True).tolist()
                    logger.info(
                        f"[FILE_UPLOAD] 单元格内换行预处理: {newline_count} 个单元格含换行符，已替换为空格"
                    )
                    for i, line in enumerate(raw_log_lines[:3]):
                        preview = line[:300] + ("..." if len(line) > 300 else "")
                        logger.info(
                            f"[FILE_UPLOAD] 预处理后样例[{i+1}/{min(3, len(raw_log_lines))}]: {preview}"
                        )
                else:
                    raw_log_lines = raw_series.tolist()
                    logger.debug("[FILE_UPLOAD] 单元格内无换行符，无需预处理")

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
        
    except ImportError:
        logger.error("[FILE_UPLOAD] pandas 未安装，无法读取 Excel 数据")
        await cl.Message(content="⚠️ 系统缺少 Excel 解析库 (pandas)，请联系管理员。").send()
    except Exception as excel_read_err:
        logger.error(f"[FILE_UPLOAD] 读取 Excel 数据表格失败: {excel_read_err}")
        await cl.Message(content=f"⚠️ 读取 Excel 文件失败：{excel_read_err}").send()