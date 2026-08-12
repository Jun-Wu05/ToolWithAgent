"""把 Planner 决策和 ExecutionReport 渲染为统一 Chainlit 响应。"""

from __future__ import annotations

import chainlit as cl

from web.planner_models import ConfigExportArtifact, ExecutionReport, PlanDecision, StepStatus


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
    """只发送一次步骤汇总，并为最终配置产物附加一个下载文件。"""
    status_icon = {
        StepStatus.SUCCESS: "✅",
        StepStatus.NEEDS_INPUT: "💡",
        StepStatus.FAILED: "❌",
    }
    lines = []
    export_payload = None
    for result in execution_report.results:
        detail = result.message or result.error_code or result.status.value
        lines.append(f"- {status_icon[result.status]} `{result.step_id}`（{result.operation_type}）：{detail}")
        if result.artifact and result.artifact.artifact_type == "config_export":
            export_payload = result.artifact.content
    elements = []
    if export_payload is not None:
        content = export_payload if isinstance(export_payload, bytes) else str(export_payload).encode("utf-8")
        elements.append(cl.File(name=f"{execution_report.plan_id}_config.txt", content=content, mime="text/plain"))
    await cl.Message(
        content=f"计划 `{execution_report.plan_id}` 执行结果：\n\n" + "\n".join(lines),
        elements=elements,
    ).send()

