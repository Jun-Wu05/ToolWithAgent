"""把 Planner 决策和 ExecutionReport 渲染为统一 Chainlit 响应。"""

from __future__ import annotations

import io
import json
from datetime import datetime

import chainlit as cl
import pandas as pd

from agent.shared.event_classify import THREAT_EVENT_NAMES
from agent.shared.logger import get_logger
from application.clarification import ClarificationRunner, compose_clarification
from application.threat_report import refresh_report_event_annotations
from web.parsers import create_dataframe_elements
from contracts.planner_models import ExecutionReport, PlanDecision, StepStatus
from contracts.session_facts import SessionFacts
from web.utils import render_log_parser_result


logger = get_logger("plan_renderer")

_THREAT_ENUM_STEP = "threat-chain-enum"
_THREAT_MAPPING_STEP = "threat-chain-map"
_THREAT_FILL_STEP = "threat-chain-fill"
_PRIMARY_REPORT_ANCHOR_KEY = "primary_field_mapping_report"


def _escape_markdown_cell(value: object) -> str:
    """转义 GFM 表格动态单元格，并将换行保留为单元格内换行。"""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def _annotation_group(row) -> int:
    """威胁事件优先、普通事件随后、待确认状态最后。"""
    if row.status == "uncertain":
        return 2
    return 0 if row.event_name in THREAT_EVENT_NAMES else 1


def _render_event_annotation_block(annotations, *, threat_pending: bool = False) -> str:
    """事件名称标注明细（#126）：以 Markdown 块渲染，位于映射表格上方。"""
    rows = [
        "🏷️ **事件名称标注**（自动写入，事件级别按绑定联动）",
        "",
        "| 子规则 | 事件名称 | 事件级别 | 威胁来源字段 | 威胁类型 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in sorted(annotations, key=_annotation_group):
        if item.status == "judged":
            event_name = item.event_name or "—"
            event_level = item.event_level or "—"
        else:
            event_name = "⚠️ 待人工确认"
            event_level = "—"
        threat_is_pending = (
            threat_pending
            and item.status == "judged"
            and item.event_name in THREAT_EVENT_NAMES
            and not item.threat_source_field
            and not item.threat_types
        )
        source_field = (
            "⏳ 生成中" if threat_is_pending else item.threat_source_field or "—"
        )
        threat_types = (
            "⏳ 生成中" if threat_is_pending else "、".join(item.threat_types) or "—"
        )
        cells = (
            item.rule_name,
            event_name,
            event_level,
            source_field,
            threat_types,
        )
        rows.append("| " + " | ".join(_escape_markdown_cell(cell) for cell in cells) + " |")
    return "\n".join(rows)


def _append_markdown_block(lines: list[str], block: str) -> None:
    """markdown 表格/详情块前后补空行（#195）。

    GFM 中表格不能中断段落：与相邻步骤 bullet 之间缺空行时，
    表格行成为列表项的 lazy continuation，整段被压成一行。
    """
    if lines:
        lines.append("")
    lines.append(block)
    lines.append("")


def _download_filename(kind: str, timestamp: str) -> str:
    """按产物语义生成用户可见下载名。"""
    names = {
        "log_classification": f"logclassification_{timestamp}.json",
        "enum_values": f"enumvalues_{timestamp}.json",
        "threat_mapping": f"threatmapping_{timestamp}.xlsx",
        "mapped_config": f"fieldmapped_config_{timestamp}.txt",
        "mapped_sub_rules": f"fieldmapped_subrules_{timestamp}.txt",
        "enummapping_config": f"enummapping_config_{timestamp}.txt",
        "threatmapping_config": f"threatmapping_config_{timestamp}.txt",
        "cancelmapping_config": f"cancelmapping_config_{timestamp}.txt",
        "current_config": f"current_config_{timestamp}.txt",
        "mappedconfig_subrules": f"mappedconfig_subrules_{timestamp}.txt",
        "mappedconfig_mainrules": f"mappedconfig_mainrules_{timestamp}.txt",
        "unmappedconfig_subrules": f"unmappedconfig_subrules_{timestamp}.txt",
        "field_adjusted_config": f"fieldadjusted_config_{timestamp}.txt",
    }
    if kind in names:
        return names[kind]
    raise ValueError(f"不支持的下载产物类型: {kind}")


def _threat_chain_download_step_ids(
    execution_report: ExecutionReport,
) -> set[str] | None:
    """完整威胁链只公开映射表和最终配置；非该链路保持原下载策略。"""
    result_by_id = {result.step_id: result for result in execution_report.results}
    if not ({_THREAT_ENUM_STEP, _THREAT_MAPPING_STEP} & result_by_id.keys()):
        return None
    final = result_by_id.get(_THREAT_FILL_STEP)
    if final is None or final.status != StepStatus.SUCCESS:
        return set()
    return {_THREAT_MAPPING_STEP, _THREAT_FILL_STEP}


def _build_result_actions(execution_report: ExecutionReport) -> list[cl.Action]:
    """根据成功产物挂载既有类型化动作，不在渲染器内执行领域逻辑。"""
    action_specs: list[tuple[str, str, str]] = []
    for result in execution_report.results:
        if result.status != StepStatus.SUCCESS or result.artifact is None:
            continue
        if result.artifact.artifact_type == "log_classification":
            action_specs.extend(
                [
                    ("apply_field_mapping", "标准字段映射", "基于已识别日志字段执行标准字段映射"),
                    ("export_rules", "生成入口规则", "生成并下载日志入口解析规则"),
                    ("export_sub_rules", "生成子规则", "生成并下载日志子解析规则"),
                ]
            )
        elif result.artifact.artifact_type == "field_mapping":
            action_specs.append(
                ("export_mapped_sub_rules", "生成映射后子规则", "生成并下载标准字段映射后的子规则")
            )

    seen: set[str] = set()
    return [
        cl.Action(name=name, label=label, description=description, payload={})
        for name, label, description in action_specs
        if not (name in seen or seen.add(name))
    ]


async def render_decision(
    decision: PlanDecision,
    *,
    session_facts: SessionFacts | None = None,
    clarification_runner: ClarificationRunner | None = None,
) -> None:
    """渲染澄清或帮助决策；执行决策必须交给 PlanExecutor。"""
    if decision.decision == "proposal":
        steps = "\n".join(
            f"{position}. `{step.type}`" for position, step in enumerate(decision.steps, 1)
        )
        choices = "\n".join(f"- {choice}" for choice in decision.choices)
        await cl.Message(
            content=(
                f"📋 {decision.question}\n\n计划步骤：\n{steps}"
                f"\n\n可选：\n{choices}"
            )
        ).send()
        return
    if decision.decision == "clarification":
        choices = "\n".join(f"- {choice}" for choice in decision.choices)
        suffix = f"\n\n可选：\n{choices}" if choices else ""
        explanation = decision.question
        if session_facts is not None:
            explanation = (
                await compose_clarification(
                    "clarification",
                    session_facts,
                    decision.reason_code,
                    decision.choices,
                    "",
                    runner=clarification_runner,
                )
                or explanation
            )
        await cl.Message(content=f"💡 {explanation}{suffix}").send()
        return
    if decision.decision == "guidance":
        # 信息型问题作答（#149）：planner 从会话事实直接生成的答案；
        # 无 answer 时回退为能力说明。
        if decision.answer:
            await cl.Message(content=f"📖 {decision.answer}").send()
            return
        await cl.Message(content="我可以处理日志类型提取、字段映射、枚举提取、威胁映射、填充、取消映射和导出。请说明目标与数据来源。").send()
        return
    raise ValueError("执行或控制决策不能直接渲染")


def build_execution_report_content(
    execution_report: ExecutionReport,
    *,
    threat_pending: bool = False,
    clarification_text: str | None = None,
) -> str:
    """构造可原地刷新的报告正文，不创建表格、下载或动作元素。"""
    status_icon = {
        StepStatus.SUCCESS: "✅",
        StepStatus.NEEDS_INPUT: "💡",
        StepStatus.FAILED: "❌",
    }
    lines = []
    pending_clarification = clarification_text
    for result in execution_report.results:
        detail = result.message or result.error_code or result.status.value
        if result.status == StepStatus.NEEDS_INPUT and pending_clarification is not None:
            detail = pending_clarification
            if result.choices:
                detail = f"{detail} 可选：{'、'.join(result.choices)}"
            pending_clarification = None
        if result.recovered:
            detail = f"{detail}（已自动重试）"
        lines.append(f"- {status_icon[result.status]} `{result.step_id}`（{result.operation_type}）：{detail}")
        artifact = result.artifact
        if artifact is None:
            continue
        if artifact.artifact_type == "field_mapping" and artifact.event_annotations:
            _append_markdown_block(
                lines,
                _render_event_annotation_block(
                    artifact.event_annotations, threat_pending=threat_pending
                ),
            )
        elif artifact.artifact_type == "log_classification":
            _append_markdown_block(
                lines, render_log_parser_result(artifact.classification, None)
            )
    return f"计划 `{execution_report.plan_id}` 执行结果：\n\n" + "\n".join(lines)


async def update_execution_report_message(message, execution_report: ExecutionReport) -> None:
    """仅用最终报告更新既有主消息，避免重复创建任何附件元素。"""
    message.content = build_execution_report_content(execution_report)
    await message.update()


def remember_primary_report(message, execution_report: ExecutionReport) -> None:
    """在当前 Chainlit 会话保存可跨轮更新的字段映射主报告。"""
    cl.user_session.set(_PRIMARY_REPORT_ANCHOR_KEY, (message, execution_report))


def clear_primary_report_anchor() -> None:
    """主数据切换或清空时废弃旧报告锚点。"""
    cl.user_session.set(_PRIMARY_REPORT_ANCHOR_KEY, None)


async def refresh_primary_report_anchor(
    execution_report: ExecutionReport, final_config
) -> bool:
    """威胁类型链路成功后用最终配置原地更新既有五列表格。"""
    fill_succeeded = any(
        result.step_id == _THREAT_FILL_STEP and result.status == StepStatus.SUCCESS
        for result in execution_report.results
    )
    if not fill_succeeded:
        return False
    anchor = cl.user_session.get(_PRIMARY_REPORT_ANCHOR_KEY)
    if not anchor:
        return False
    message, primary_report = anchor
    refreshed = refresh_report_event_annotations(
        primary_report,
        final_config,
        chain_succeeded=True,
    )
    await update_execution_report_message(message, refreshed)
    remember_primary_report(message, refreshed)
    return True


async def render_execution_report(
    execution_report: ExecutionReport,
    *,
    threat_pending: bool = False,
    session_facts: SessionFacts | None = None,
    clarification_runner: ClarificationRunner | None = None,
):
    """先发送步骤汇总，再按顺序纵向发送表格和下载，并返回主消息句柄。"""
    clarification_text = None
    needs_input = next(
        (
            result
            for result in execution_report.results
            if result.status == StepStatus.NEEDS_INPUT
        ),
        None,
    )
    if session_facts is not None and needs_input is not None:
        recovered_count = sum(result.recovered for result in execution_report.results)
        recovery_summary = (
            f"retry_as_is={recovered_count}" if recovered_count else ""
        )
        clarification_text = await compose_clarification(
            "needs_input",
            session_facts,
            needs_input.error_code,
            needs_input.choices,
            recovery_summary,
            runner=clarification_runner,
        )
    dataframe_elements, download_elements = [], []
    actions = _build_result_actions(execution_report)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    field_mapping_downloads: list[tuple[str, str, bytes]] = []
    threat_download_steps = _threat_chain_download_step_ids(execution_report)
    for result in execution_report.results:
        artifact = result.artifact
        if artifact is None:
            continue
        download_allowed = (
            threat_download_steps is None or result.step_id in threat_download_steps
        )
        if artifact.artifact_type == "config_export":
            if not download_allowed:
                continue
            content = artifact.content if isinstance(artifact.content, bytes) else str(artifact.content).encode("utf-8")
            download_elements.append(
                cl.File(
                    name=_download_filename(artifact.download_kind, timestamp),
                    content=content,
                    mime="text/plain",
                )
            )
        elif artifact.artifact_type == "field_mapping":
            # 字段映射产物必须落表展示，否则用户只看到一行「步骤执行成功」。
            rows = [mapping.model_dump(by_alias=True) for mapping in artifact.mappings]
            dataframe_elements.extend(create_dataframe_elements(rows))
            if artifact.download_kind and artifact.download_content:
                field_mapping_downloads.append(
                    (
                        artifact.download_kind,
                        _download_filename(artifact.download_kind, timestamp),
                        artifact.download_content.encode("utf-8"),
                    )
                )
        elif artifact.artifact_type == "threat_mapping":
            rows = [mapping.model_dump(by_alias=True) for mapping in artifact.mappings]
            dataframe_elements.extend(create_dataframe_elements(rows))
            if download_allowed:
                dataframe = pd.DataFrame(rows, columns=["mappingType", "orgValue", "mappingValue"])
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    dataframe.to_excel(writer, index=False, sheet_name="threat_mapping")
                download_elements.append(
                    cl.File(
                        name=_download_filename("threat_mapping", timestamp),
                        content=output.getvalue(),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                )
        elif artifact.artifact_type == "enum_values":
            # 枚举提取产物落表展示，并附可下载文件，保留旧的「下载行为」。
            rows = [{"枚举值": value} for value in artifact.values]
            dataframe_elements.extend(create_dataframe_elements(rows))
            if download_allowed:
                download_elements.append(
                    cl.File(
                        name=_download_filename("enum_values", timestamp),
                        content=json.dumps(
                            {
                                "field": artifact.field,
                                "regex": artifact.regex,
                                "original_log": list(artifact.original_log),
                                "value": list(artifact.values),
                            },
                            ensure_ascii=False,
                            indent=4,
                        ).encode("utf-8"),
                        mime="application/json",
                    )
                )
        elif artifact.artifact_type == "log_classification":
            download_elements.append(
                cl.File(
                    name=_download_filename("log_classification", timestamp),
                    content=json.dumps(
                        artifact.classification,
                        ensure_ascii=False,
                        indent=4,
                    ).encode("utf-8"),
                    mime="application/json",
                )
            )
    message_kwargs = {
        "content": build_execution_report_content(
            execution_report,
            threat_pending=threat_pending,
            clarification_text=clarification_text,
        ),
        "elements": [],
    }
    if actions:
        message_kwargs["actions"] = actions
    main_message = cl.Message(**message_kwargs)
    await main_message.send()

    for element_group in (dataframe_elements, download_elements):
        for element in element_group:
            await cl.Message(content="", elements=[element]).send()

    if any(
        result.error_code == "data_source_fields_required"
        for result in execution_report.results
    ):
        from web.rule_source_form import prompt_rule_source_fields

        await prompt_rule_source_fields()

    for download_kind, file_name, content in field_mapping_downloads:
        title = (
            "✅ **字段映射已回填到上传配置**"
            if download_kind == "mapped_config"
            else "✅ **字段映射已写入解析子规则**"
        )
        logger.info(
            "[RENDER_FIELD_MAPPING] 准备发送字段映射下载: "
            "plan_id=%s download_kind=%s file_name=%s content_bytes=%s",
            execution_report.plan_id,
            download_kind,
            file_name,
            len(content),
        )
        await cl.Message(
            content=(
                f"{title}\n\n"
                f"📥 点击下载：`{file_name}`"
            ),
            elements=[
                cl.File(
                    name=file_name,
                    content=content,
                    display="inline",
                    mime="text/plain",
                )
            ],
        ).send()
        logger.info(
            "[RENDER_FIELD_MAPPING] 字段映射下载已发送: "
            "plan_id=%s download_kind=%s file_name=%s",
            execution_report.plan_id,
            download_kind,
            file_name,
        )
    return main_message
