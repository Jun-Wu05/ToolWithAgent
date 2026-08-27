"""把 Planner 决策和 ExecutionReport 渲染为统一 Chainlit 响应。"""

from __future__ import annotations

import io
import json
from datetime import datetime

import chainlit as cl
import pandas as pd

from agent.shared.logger import get_logger
from web.parsers import create_dataframe_elements
from contracts.planner_models import ExecutionReport, PlanDecision, StepStatus
from web.utils import render_log_parser_result


logger = get_logger("plan_renderer")


def _render_event_annotation_block(annotations) -> str:
    """事件名称标注明细（#126）：以 Markdown 块渲染，位于映射表格上方。"""
    rows = [
        "🏷️ **事件名称标注**（自动写入，事件级别按绑定联动）",
        "",
        "| 子规则 | 事件名称 | 事件级别 |",
        "| --- | --- | --- |",
    ]
    for item in annotations:
        if item.status == "judged":
            rows.append(f"| {item.rule_name} | {item.event_name} | {item.event_level} |")
        else:
            rows.append(f"| {item.rule_name} | ⚠️ 待人工确认 | — |")
    return "\n".join(rows)


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


async def render_decision(decision: PlanDecision) -> None:
    """渲染澄清或帮助决策；执行决策必须交给 PlanExecutor。"""
    if decision.decision == "clarification":
        choices = "\n".join(f"- {choice}" for choice in decision.choices)
        suffix = f"\n\n可选：\n{choices}" if choices else ""
        await cl.Message(content=f"💡 {decision.question}{suffix}").send()
        return
    if decision.decision == "guidance":
        # 信息型问题作答（#149）：planner 从会话事实直接生成的答案；
        # 无 answer 时回退为能力说明。
        if decision.answer:
            await cl.Message(content=f"📖 {decision.answer}").send()
            return
        await cl.Message(content="我可以处理日志类型提取、字段映射、枚举提取、威胁映射、填充、取消映射和导出。请说明目标与数据来源。").send()
        return
    raise ValueError("执行决策不能直接渲染")


async def render_execution_report(execution_report: ExecutionReport) -> None:
    """发送一次步骤汇总；七类产物按类型附表格或下载，复合计划全部进同一条汇总。"""
    status_icon = {
        StepStatus.SUCCESS: "✅",
        StepStatus.NEEDS_INPUT: "💡",
        StepStatus.FAILED: "❌",
    }
    lines = []
    elements = []
    actions = _build_result_actions(execution_report)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    field_mapping_downloads: list[tuple[str, str, bytes]] = []
    for result in execution_report.results:
        detail = result.message or result.error_code or result.status.value
        lines.append(f"- {status_icon[result.status]} `{result.step_id}`（{result.operation_type}）：{detail}")
        artifact = result.artifact
        if artifact is None:
            continue
        if artifact.artifact_type == "config_export":
            content = artifact.content if isinstance(artifact.content, bytes) else str(artifact.content).encode("utf-8")
            elements.append(
                cl.File(
                    name=_download_filename(artifact.download_kind, timestamp),
                    content=content,
                    mime="text/plain",
                )
            )
        elif artifact.artifact_type == "field_mapping":
            # 字段映射产物必须落表展示，否则用户只看到一行「步骤执行成功」。
            rows = [mapping.model_dump(by_alias=True) for mapping in artifact.mappings]
            elements.extend(create_dataframe_elements(rows))
            # 标注明细以内容块渲染，位于表格元素上方（#126 展示分离）
            if artifact.event_annotations:
                lines.append(_render_event_annotation_block(artifact.event_annotations))
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
            elements.extend(create_dataframe_elements(rows))
            dataframe = pd.DataFrame(rows, columns=["mappingType", "orgValue", "mappingValue"])
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                dataframe.to_excel(writer, index=False, sheet_name="threat_mapping")
            elements.append(
                cl.File(
                    name=_download_filename("threat_mapping", timestamp),
                    content=output.getvalue(),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            )
        elif artifact.artifact_type == "enum_values":
            # 枚举提取产物落表展示，并附可下载文件，保留旧的「下载行为」。
            rows = [{"枚举值": value} for value in artifact.values]
            elements.extend(create_dataframe_elements(rows))
            elements.append(
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
            lines.append(render_log_parser_result(artifact.classification, None))
            elements.append(
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
        "content": f"计划 `{execution_report.plan_id}` 执行结果：\n\n" + "\n".join(lines),
        "elements": elements,
    }
    if actions:
        message_kwargs["actions"] = actions
    await cl.Message(**message_kwargs).send()

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
