"""Chainlit 确定性事件适配层。

有明确领域语义的按钮必须构造类型化步骤并复用 PlanExecutor；
仅生成 Excel 展示文件且不改变领域状态的按钮留在本模块渲染。
"""

import chainlit as cl
import json
import io
import re
import pandas as pd
from datetime import datetime
from agent.shared.logger import get_logger

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
    """把缺少目标字段的威胁填充按钮转换为类型化澄清决策。"""
    from web.plan_renderer import render_decision
    from web.planner_models import PlanDecision

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"带字段填充"按钮')
    if not user_session.get("last_threat_data"):
        await cl.Message(content="❌ 未找到填充数据，请先执行威胁类型映射。").send()
        return
    # 按钮没有目标字段，必须追问；不得开启会劫持下一条文本的模式状态。
    await render_decision(
        PlanDecision(
            decision="clarification",
            reason_code="target_field_required",
            question="请用自然语言明确目标字段，例如：把威胁映射填充到 threat_type。",
        )
    )

@cl.action_callback("confirm_fill")
async def on_confirm_fill(action: cl.Action):
    """拒绝消费旧字段映射结果，并提示用户发起新的显式字段映射计划。"""
    from web.plan_renderer import render_decision
    from web.planner_models import PlanDecision

    logger.info('[ACTION] 用户点击"确认填充"按钮')
    await render_decision(
        PlanDecision(
            decision="clarification",
            reason_code="current_dependency_required",
            question="旧字段映射结果不能直接用于本次填充。请发送“执行标准字段映射”，系统会在同一计划中完成映射与回写。",
        )
    )

@cl.action_callback("start_enum_fill")
async def on_start_enum_fill(action: cl.Action):
    """把枚举填充按钮转换为显式 FillStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from web.planner_models import FillStep
    from web.session_facts import build_session_facts

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"开始枚举填充"按钮')
    session_facts = build_session_facts(user_session)
    if not session_facts.enum_mapping_target_fields:
        await cl.Message(content="❌ 枚举映射表丢失，请重新上传 Excel 映射表。").send()
        return
    config_ref = (
        "session.mapped_sub_rules"
        if "session.mapped_sub_rules" in session_facts.available_config_refs
        else "session.decoded_config"
    )
    step = FillStep(
        step_id="enum-fill",
        type="fill",
        fill_kind="enum",
        target_fields=session_facts.enum_mapping_target_fields,
        source_ref="session.enum_mapping_table",
        config_ref=config_ref,
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-enum-fill",
        steps=(step,),
    )

@cl.action_callback("export_rules")
async def on_export_rules(action: cl.Action):
    """把入口规则导出按钮转换为 ExportStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from web.planner_models import ExportStep

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"导出入口规则"按钮')
    step = ExportStep(
        step_id="export-entry-rules",
        type="export",
        source_ref="session.log_classification.entry_rules",
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-export-entry-rules",
        steps=(step,),
    )

@cl.action_callback("export_sub_rules")
async def on_export_sub_rules(action: cl.Action):
    """把子规则导出按钮转换为 ExportStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from web.planner_models import ExportStep

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"导出子规则"按钮')
    step = ExportStep(
        step_id="export-sub-rules",
        type="export",
        source_ref="session.log_classification.sub_rules",
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-export-sub-rules",
        steps=(step,),
    )

@cl.action_callback("apply_field_mapping")
async def on_apply_field_mapping(action: cl.Action):
    """把标准字段映射按钮转换为 FieldMappingStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from web.planner_models import FieldMappingStep
    from web.session_facts import build_session_facts

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"标准字段映射"按钮')
    session_facts = build_session_facts(user_session)
    if not session_facts.available_fields:
        await cl.Message(content="❌ 当前没有可映射字段，请先上传并解析日志。").send()
        return
    step = FieldMappingStep(
        step_id="field-mapping",
        type="field_mapping",
        source_ref="session.fields",
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-field-mapping",
        steps=(step,),
    )

@cl.action_callback("export_mapped_sub_rules")
async def on_export_mapped_sub_rules(action: cl.Action):
    """把配置导出按钮转换为 ExportStep 并复用统一执行器。"""
    from web.deterministic_plan import execute_deterministic_plan
    from web.planner_models import ExportStep

    user_session = cl.user_session.get("user_session")
    logger.info('[ACTION] 用户点击"导出映射后子规则"按钮')
    step = ExportStep(
        step_id="export",
        type="export",
        source_ref="session.mapped_sub_rules",
    )
    await execute_deterministic_plan(
        user_session=user_session,
        team=user_session.get("team"),
        plan_id="button-export-mapped-sub-rules",
        steps=(step,),
    )

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
