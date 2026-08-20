"""Chainlit 文件事件适配层。

文件上传只解析内容并建立结构化会话事实；不得执行自然语言意图判断，
也不得开启会劫持下一条消息的填充状态。
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
from agent.tools import flatten_enum_mappings, read_enum_mappings_from_excel
from web.parsers import create_dataframe_elements
from web.session_state import PrimaryDatasetSnapshot


# 枚举映射表列头关键词（唯一实现；utils 版重复副本已删除）
_ENUM_HEADER_KEYWORDS: Set[str] = {
    "mappingtype", "orgvalue", "mappingvalue",
    "原始值", "映射值", "映射类型",
    "目标字段", "target_field", "targetfield"
}


_PRIMARY_DATASET_STATE_KEYS = (
    "decoded_data",
    "decoded_fields",
    "original_log",
    "simplified_data",
    "decoded_text",
    "raw_log_lines",
    "uploaded_file_name",
    "uploaded_file_time",
    "raw_base64",
    "enum_excel_path",
    "enum_preview",
    "enum_mapping_sheets",
    "enum_fill_contributions",
    "stale_enum_config_refs",
    "enum_pending_refills",
    "last_mapping_data",
    "excel_data",
    "excel_filename",
    "last_threat_data",
    "last_enum_extract_result",
    "latest_threat_artifact",
    "latest_enum_artifact",
    "log_classification",
    "mapped_sub_rules",
    "sub_rule_mapping_results",
    "batch_mapping_results",
    "conversation_history",
)


def _commit_primary_dataset(user_session, snapshot: PrimaryDatasetSnapshot) -> None:
    """兼容 SessionState 与旧字典测试替身，集中提交主数据快照。"""
    replace = getattr(user_session, "replace_primary_dataset", None)
    if callable(replace):
        replace(snapshot)
        return
    staged_values = {
        "decoded_data": snapshot.decoded_data,
        "decoded_fields": list(snapshot.decoded_fields),
        "original_log": snapshot.original_log,
        "simplified_data": snapshot.simplified_data,
        "decoded_text": snapshot.decoded_text,
        "raw_log_lines": snapshot.raw_log_lines,
        "raw_base64": snapshot.raw_base64,
        "uploaded_file_name": snapshot.uploaded_file_name,
        "uploaded_file_time": snapshot.uploaded_file_time,
        "conversation_history": [],
    }
    for key in _PRIMARY_DATASET_STATE_KEYS:
        user_session.pop(key, None)
    user_session.update(staged_values)


def _commit_enum_workbook(user_session, excel_path: str, uploaded_sheets: dict) -> list:
    """按 Sheet 原子合并枚举附件，并返回完整集合的兼容预览。"""
    existing_sheets = user_session.get("enum_mapping_sheets", {}) or {}
    merged_sheets = {
        name: [dict(row) for row in rows]
        for name, rows in existing_sheets.items()
    }
    merged_sheets.update(
        {
            name: [dict(row) for row in rows]
            for name, rows in uploaded_sheets.items()
        }
    )
    preview = flatten_enum_mappings(merged_sheets)
    contributions = user_session.get("enum_fill_contributions", {}) or {}
    stale_refs = set(user_session.get("stale_enum_config_refs", set()) or set())
    stale_refs.update(contributions)
    pending_refills = {
        config_ref: set(sheet_names)
        for config_ref, sheet_names in (
            user_session.get("enum_pending_refills", {}) or {}
        ).items()
    }
    for config_ref in contributions:
        pending_refills.setdefault(config_ref, set()).update(uploaded_sheets)
    user_session["enum_mapping_sheets"] = merged_sheets
    user_session["enum_preview"] = preview
    user_session["enum_excel_path"] = excel_path
    user_session["stale_enum_config_refs"] = stale_refs
    user_session["enum_pending_refills"] = pending_refills
    return preview


async def handle_file_upload(user_session, element):
    """解析上传文件并更新会话事实，不直接触发业务执行。"""
    try:
        # 获取文件内容（委托 file_handler）
        file_content = read_element_content(element)

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

                # 是枚举映射表 → 全工作簿解析成功后再原子合并到当前附件集合
                uploaded_sheets = read_enum_mappings_from_excel(excel_path)
                enum_preview = _commit_enum_workbook(
                    user_session,
                    excel_path,
                    uploaded_sheets,
                )
                logger.info(f"[FILE_UPLOAD] 枚举映射表确认，预览条数: {len(enum_preview) if enum_preview else 0}")

                if not enum_preview:
                    await cl.Message(content=f"⚠️ 枚举映射表 `{file_name}` 未读取到有效映射规则").send()
                    return

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
            file_name_val = get_element_file_name(element)
            file_time = datetime.now().strftime("%H:%M:%S")
            snapshot = PrimaryDatasetSnapshot(
                decoded_data=result["decoded_json"],
                decoded_fields=result["fields"],
                original_log=result["original_log"],
                simplified_data=build_simplified_data(result),
                decoded_text=result.get("decoded_text", ""),
                raw_base64=file_content,
                uploaded_file_name=file_name_val,
                uploaded_file_time=file_time,
            )
            _commit_primary_dataset(user_session, snapshot)
            logger.info(f"[FILE_UPLOAD] 记录上传文件元信息: name={file_name_val}, time={file_time}")

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

    数据表格必须包含"原始日志"列，否则在写入任何会话状态前拒绝（回归 #78）。

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

        # 先定位"原始日志"列；缺失即拒绝，不得把列头当作字段进入后续映射。
        raw_log_column = next((col for col in df.columns if "原始日志" in str(col)), None)
        if raw_log_column is None:
            logger.warning(
                f"[FILE_UPLOAD] 数据表格缺少\"原始日志\"列，已拒绝: file={file_name} "
                f"columns={list(df.columns)}"
            )
            await cl.Message(
                content=(
                    f"❌ Excel 文件 `{file_name}` 缺少\"原始日志\"列。\n\n"
                    "上传正确的excel，应包含原始日志一列。"
                )
            ).send()
            return

        # 将 DataFrame 转为结构化数据，填入 user_session（与 Base64 解码流程对齐）
        records = df.fillna("").to_dict(orient="records")
        fields = list(df.columns)
        # original_log 必须是字符串列表，供类型化枚举与日志步骤稳定拼接。
        original_log = [json.dumps(r, ensure_ascii=False) for r in records]
        decoded_text = df.to_string(index=False)

        file_time = datetime.now().strftime("%H:%M:%S")

        # 提取"原始日志"列，供 LogParserAgent 精简输入使用
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

                logger.info(f"[FILE_UPLOAD] 提取\"原始日志\"列({col})：{len(raw_log_lines)} 行")
                break

        snapshot = PrimaryDatasetSnapshot(
            decoded_data=records,
            decoded_fields=fields,
            original_log=original_log,
            simplified_data={
                "fields": fields,
                "original_log_sample": decoded_text[:2000],
            },
            decoded_text=decoded_text,
            raw_log_lines=raw_log_lines,
            uploaded_file_name=file_name,
            uploaded_file_time=file_time,
        )
        _commit_primary_dataset(user_session, snapshot)

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
