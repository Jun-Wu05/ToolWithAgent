"""把 Planner 决策和 ExecutionReport 渲染为统一 Chainlit 响应。"""

from __future__ import annotations

import chainlit as cl

from agent.shared.logger import get_logger
from web.parsers import create_dataframe_elements
from web.planner_models import ConfigExportArtifact, ExecutionReport, PlanDecision, StepStatus


logger = get_logger("plan_renderer")


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
    """发送一次步骤汇总；字段映射附映射表，配置导出附下载文件。"""
    status_icon = {
        StepStatus.SUCCESS: "✅",
        StepStatus.NEEDS_INPUT: "💡",
        StepStatus.FAILED: "❌",
    }
    lines = []
    elements = []
    mapped_config_downloads: list[tuple[str, bytes]] = []
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
            if artifact.filled_config:
                mapped_config_downloads.append(
                    (
                        f"{execution_report.plan_id}_mapped_config.txt",
                        artifact.filled_config.encode("utf-8"),
                    )
                )
    await cl.Message(
        content=f"计划 `{execution_report.plan_id}` 执行结果：\n\n" + "\n".join(lines),
        elements=elements,
    ).send()

    for file_name, content in mapped_config_downloads:
        logger.info(
            "[RENDER_FIELD_MAPPING] 准备发送回填配置下载: "
            "plan_id=%s file_name=%s content_bytes=%s",
            execution_report.plan_id,
            file_name,
            len(content),
        )
        await cl.Message(
            content=(
                "✅ **字段映射已回填到上传配置**\n\n"
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
            "[RENDER_FIELD_MAPPING] 回填配置下载已发送: "
            "plan_id=%s file_name=%s",
            execution_report.plan_id,
            file_name,
        )
