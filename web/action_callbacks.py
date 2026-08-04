"""
Chainlit Action 回调 - 从 chainlit_app.py 提取

本模块包含所有 Action 回调函数（9个）：
- 字段映射填充
- 威胁填充模式
- 枚举填充模式
- 规则导出
- 标准字段映射
- Excel 导出
"""

import chainlit as cl
import json
import io
import re
import pandas as pd
from datetime import datetime
from agent.shared.logger import get_logger
from agent.shared.field_mapping import get_field_mapping_handler
from agent.shared.threat_fill import export_to_base64
from agent.tools.rule_generator import (
    generate_rules,
    rules_to_base64_text,
    generate_sub_rules,
    apply_field_mapping_to_sub_rules
)
from agent.tools.standard_mapper import _load_object_mapping

logger = get_logger("action_callbacks")


def _build_retrieval_candidates_map(mapping_results: list) -> dict[str, str]:
    """为导出 xlsx 重新检索每个原始字段的标准字段候选 top3。

    batch_retrieve_candidates 是确定性的（同缓存 + 同字段名 → 同候选），
    因此导出时重新检索一次即可还原 LLM 输入中注入的候选，
    无需侵入映射流程保存中间结果。

    Args:
        mapping_results: 子规则映射结果列表（含 rule_name + mappings[原始字段名]）

    Returns:
        {原始字段名: "候选A(0.71) / 候选B(0.69) / 候选C(0.64)"} 字典。
        检索失败或无候选时对应值为空字符串。
    """
    # 收集所有原始字段名（去重，保持顺序）
    all_fields: list[str] = []
    seen: set[str] = set()
    for mr in mapping_results:
        for m in mr.get("mappings", []):
            f = m.get("原始字段名", "")
            if f and f not in seen:
                all_fields.append(f)
                seen.add(f)

    if not all_fields:
        return {}

    candidates_map: dict[str, str] = {f: "" for f in all_fields}

    try:
        from agent.core.field_retriever import batch_retrieve_candidates
        raw = batch_retrieve_candidates(all_fields, top_k=5)
    except Exception as e:
        logger.warning(f"[EXPORT] 检索候选失败，候选列留空: {e}")
        return candidates_map

    if not raw or not raw.strip():
        return candidates_map

    # 解析紧凑格式：每行 "field → cand1(...) | cand2(...) | cand3(...)"
    # 候选格式形如 "威胁等级(0.71, threat_level)"，去掉括号内冗余只保留"候选名(分数)"
    for line in raw.splitlines():
        line = line.strip()
        if not line or "→" not in line:
            continue
        field_part, cand_part = line.split("→", 1)
        field = field_part.strip()
        cands = [c.strip() for c in cand_part.split("|") if c.strip()]
        # 把 "威胁等级(0.71, threat_level)" 规整为 "威胁等级(0.71)"
        cleaned: list[str] = []
        for c in cands:
            m = re.match(r"^(.+?)\(([\d.]+)", c)
            cleaned.append(f"{m.group(1)}({m.group(2)})" if m else c)
        candidates_map[field] = " / ".join(cleaned)

    return candidates_map


@cl.action_callback("fill_threat_with_field")
async def on_fill_threat_with_field(action: cl.Action):
    """用户点击"带字段填充"按钮 - 进入威胁填充模式"""
    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"带字段填充"按钮')
    
    last_threat_data = user_session.get("last_threat_data")
    logger.info(f"[ACTION] 威胁填充模式，表格数据检查: {last_threat_data is not None}")

    if not last_threat_data:
        await cl.Message(content="❌ 未找到填充数据，请先执行威胁类型映射。").send()
        return

    # 保存表格数据到会话 + 进入威胁填充模式
    user_session["threat_mapping_table"] = last_threat_data
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
```"""
    ).send()


@cl.action_callback("confirm_fill")
async def on_confirm_fill(action: cl.Action):
    """用户点击"确认填充"按钮 - 字段映射填充"""
    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"确认填充"按钮')
    
    mapping_data = user_session.get("last_mapping_data")

    if not mapping_data:
        logger.warning("[ACTION] 未找到映射数据")
        await cl.Message(content="❌ 未找到映射数据，请先执行字段映射。").send()
        return
    
    logger.info(f"[ACTION] 提取字段映射: {len(mapping_data)} 条")
    
    # 执行字段填充
    try:
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
    """用户点击"开始枚举填充"按钮 - 进入枚举填充模式"""
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


@cl.action_callback("export_rules")
async def on_export_rules(action: cl.Action):
    """用户点击"导出入口规则"按钮"""
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
    """用户点击"导出子规则"按钮"""
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


@cl.action_callback("apply_field_mapping")
async def on_apply_field_mapping(action: cl.Action):
    """用户点击"标准字段映射"按钮"""
    user_session = cl.user_session.get("user_session")
    classification = user_session.get("log_classification")
    logger.info('[ACTION] 用户点击"标准字段映射"按钮')
    
    if not classification or not isinstance(classification, dict):
        await cl.Message(content="❌ 未找到日志分类结果，请先执行日志解析。").send()
        return
    
    try:
        # 1. 生成子规则（用于获取字段列表）
        logger.info("[ACTION] 生成子规则用于字段映射")
        
        raw_log_lines = user_session.get("raw_log_lines", [])
        all_logs_str = "\n".join(str(line) for line in raw_log_lines) if raw_log_lines else ""
        
        sub_rules = generate_sub_rules(classification, all_logs_str=all_logs_str)
        
        if not sub_rules:
            await cl.Message(content="❌ 未生成任何子规则，无法进行字段映射。").send()
            return
        
        # 2. 提取所有字段（排除 original_log / 日志类型 元字段）
        # CHANGED (2026-07-28): 复用 field_source，与自然语言映射路径共用同一字段来源
        from web.field_source import extract_log_fields_for_mapping
from agent.tools.rule_generator.field_mapping import EXCLUDED_FIELD_INDICES
        all_fields = extract_log_fields_for_mapping(classification, raw_log_lines)

        if not all_fields:
            # 回退：field_source 内部已生成 sub_rules，若仍无字段则说明规则为空
            await cl.Message(content="❌ 未从日志中提取到任何字段，无法进行字段映射。").send()
            return

        logger.info(f"[ACTION] 共提取 {len(all_fields)} 个唯一字段")
        
        # 3. 调用分批映射（委托 batch_mapping_helper）
        from web.batch_mapping_helper import run_batched_mapping
        from web.parsers import parse_json_mapping_result, create_dataframe_elements
        
        sample_logs_text = "\n".join(str(line) for line in raw_log_lines[:10]) if raw_log_lines else ""
        simplified_data = {
            "fields": all_fields,
            "original_log_sample": sample_logs_text
        }
        user_session["simplified_data"] = simplified_data
        
        BATCH_SIZE = 25
        mapping_data, total_batches = await run_batched_mapping(
            team=user_session.team,
            fields_list=all_fields,
            user_text="标准字段映射",
            user_session=user_session,
            parse_fn=parse_json_mapping_result,
            batch_size=BATCH_SIZE,
        )

        if not mapping_data:
            await cl.Message(content="❌ 字段映射失败，请重试。").send()
            return
        
        # 5. 将结果按子规则分组
        field_to_mapping = {item.get("原始字段名", ""): item for item in mapping_data}
        
        all_sub_rule_results = []
        for rule in sub_rules:
            rule_name = rule.get("name", "")
            rule_fields = [
                entry.get("index", "")
                for entry in rule.get("normalize", [])
                if entry.get("index", "") not in EXCLUDED_FIELD_INDICES
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
        
        # 7. 应用映射到子规则
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
        
        # 构建各子规则字段明细
        per_rule_lines = []
        for mr in all_sub_rule_results:
            rule_name = mr.get("rule_name", "未知")
            field_count = len(mr.get("mappings", []))
            per_rule_lines.append(f"  - `{rule_name}`：{field_count} 个字段")
        per_rule_detail = "\n".join(per_rule_lines)

        summary = (
            f"✅ **标准字段映射完成！**\n\n"
            f"📊 **映射统计：**\n"
            f"- 子规则数量：{len(all_sub_rule_results)}\n"
            f"- 总字段数：{total_fields}\n"
            f"- 匹配成功：{total_matched} 个\n"
            f"- 未匹配：{total_fields - total_matched} 个\n\n"
            f"📋 **各子规则字段明细：**\n"
            f"{per_rule_detail}\n\n"
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
        # 重新检索每个原始字段的标准字段候选 top3（确定性，还原 LLM 输入候选）
        candidates_map = _build_retrieval_candidates_map(mapping_results)

        excel_data = []
        for mr in mapping_results:
            rule_name = mr.get("rule_name", "未知")
            for m in mr.get("mappings", []):
                orig = m.get("原始字段名", "")
                excel_data.append({
                    "子规则": rule_name,
                    "原始字段": orig,
                    "标准字段": m.get("系统属性名称", ""),
                    "匹配状态": m.get("匹配状态", ""),
                    "检索候选top3": candidates_map.get(orig, ""),
                })

        df = pd.DataFrame(excel_data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='字段映射')
        output.seek(0)

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"字段映射_{date_str}.xlsx"
        
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
        # 重新检索每个原始字段的标准字段候选 top3（确定性，还原 LLM 输入候选）
        candidates_map = _build_retrieval_candidates_map(mapping_results)

        excel_data = []
        for mr in mapping_results:
            rule_name = mr.get("rule_name", "批量映射")
            for m in mr.get("mappings", []):
                orig = m.get("原始字段名", "")
                excel_data.append({
                    "子规则": rule_name,
                    "原始字段": orig,
                    "标准字段": m.get("系统属性名称", ""),
                    "匹配状态": m.get("匹配状态", ""),
                    "检索候选top3": candidates_map.get(orig, ""),
                })

        df = pd.DataFrame(excel_data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='字段映射')
        output.seek(0)

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"字段映射_批量_{date_str}.xlsx"
        
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


@cl.action_callback("export_enum_mapping_excel")
async def on_export_enum_mapping_excel(action: cl.Action):
    """导出枚举提取结果为 Excel 映射表（供用户本地编辑 mappingValue 后回填）"""
    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"导出枚举映射表"按钮')

    enum_result = user_session.get("last_enum_extract_result")
    if not enum_result:
        await cl.Message(content="❌ 未找到枚举提取结果，请先执行枚举提取。").send()
        return

    field_name = enum_result.get("field", "unknown")
    values = enum_result.get("value", [])

    if not values:
        await cl.Message(content="❌ 枚举提取结果为空，无法导出。").send()
        return

    try:
        # 构建 Excel 映射表（sheet 名 = field_name，列为 mappingType/orgValue/mappingValue）
        excel_data = [{"mappingType": "EQUAL", "orgValue": v, "mappingValue": ""} for v in values]
        df = pd.DataFrame(excel_data)

        output = io.BytesIO()
        # sheet 名最多 31 字符（Excel 限制），用 field_name
        sheet_name = field_name[:31] if len(field_name) > 31 else field_name
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        output.seek(0)

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"枚举映射表_{field_name}_{date_str}.xlsx"

        excel_file = cl.File(
            name=file_name,
            content=output.getvalue(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        await cl.Message(
            content=f"""✅ **枚举映射表已导出！**

📋 **映射表信息：**
- 目标字段（Sheet 名）：{field_name}
- 枚举值数量：{len(values)} 条

💡 **下一步操作：**
1. 下载后在本地填入 **mappingValue**（映射后的值）
2. 重新上传此 Excel 文件
3. 说「填充到{field_name}」将映射结果写入解析规则""",
            elements=[excel_file]
        ).send()

    except ImportError:
        logger.error("[ACTION] pandas 或 openpyxl 未安装")
        await cl.Message(content="❌ 系统缺少 Excel 导出库 (pandas/openpyxl)，请联系管理员。").send()
    except Exception as e:
        logger.error(f"[ACTION] 枚举映射表 Excel 导出异常: {e}")
        await cl.Message(content=f"❌ Excel 导出失败：{e}").send()