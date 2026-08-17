"""把 Planner 决策和 ExecutionReport 渲染为统一 Chainlit 响应。"""

from __future__ import annotations

import io
import json

import chainlit as cl
import pandas as pd

from agent.shared.logger import get_logger
from web.parsers import create_dataframe_elements
from contracts.planner_models import ExecutionReport, PlanDecision, StepStatus
from web.utils import render_log_parser_result


logger = get_logger("plan_renderer")


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
                cl.File(name=f"{execution_report.plan_id}_config.txt", content=content, mime="text/plain")
            )
        elif artifact.artifact_type == "field_mapping":
            # 字段映射产物必须落表展示，否则用户只看到一行「步骤执行成功」。
            rows = [mapping.model_dump(by_alias=True) for mapping in artifact.mappings]
            elements.extend(create_dataframe_elements(rows))
            if artifact.download_kind and artifact.download_content:
                field_mapping_downloads.append(
                    (
                        artifact.download_kind,
                        f"{execution_report.plan_id}_{artifact.download_kind}.txt",
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
                    name=f"{execution_report.plan_id}_threat_mapping.xlsx",
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
                    name=f"{execution_report.plan_id}_enum_values.json",
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
                    name=f"{execution_report.plan_id}_log_classification.json",
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
