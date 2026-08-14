"""把 Planner 决策和 ExecutionReport 渲染为统一 Chainlit 响应。"""

from __future__ import annotations

import chainlit as cl

from agent.shared.logger import get_logger
from web.parsers import create_dataframe_elements
from web.planner_models import ExecutionReport, PlanDecision, StepStatus


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


def _log_classification_row(type_name: str, info: object) -> dict[str, str]:
    """把日志分类条目归一为表格行，容忍不同分类结构的字段差异。"""
    feature = ""
    sample_count = ""
    if isinstance(info, dict):
        feature = str(info.get("feature") or info.get("feature_field") or "")
        samples = info.get("samples") if "samples" in info else info.get("sample")
        if isinstance(samples, list):
            sample_count = str(len(samples))
        elif samples:
            sample_count = "1"
    return {"日志类型": str(type_name), "特征字段": feature, "样本数": sample_count}


def _classification_detail_rows(classification: dict[str, object]) -> list[dict[str, str]]:
    """把当前 Pipeline 的分类明细或旧版字典统一转换为表格行。"""
    details = classification.get("classification_details")
    if isinstance(details, list):
        feature_field = str(
            classification.get("feature_field")
            or classification.get("feature_identifier")
            or classification.get("categorical_features")
            or ""
        )
        rows = []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            type_name = detail.get("logtype") or detail.get("log_type") or detail.get("type")
            if not type_name:
                continue
            samples = detail.get("real_samples") or detail.get("samples") or detail.get("sample")
            if isinstance(samples, list):
                sample_count = len(samples)
            elif samples:
                sample_count = 1
            else:
                sample_count = detail.get("count", "")
            rows.append(
                {
                    "日志类型": str(type_name),
                    "特征字段": feature_field,
                    "样本数": str(sample_count),
                    "匹配数量": str(detail.get("count") or ""),
                    "匹配规则": str(detail.get("matched_regex") or ""),
                    "覆盖率": str(detail.get("coverage_pct") or ""),
                }
            )
        return rows
    return [
        _log_classification_row(type_name, info)
        for type_name, info in classification.items()
        if type_name not in {"status", "error", "analysis"}
    ]


def _classification_details(classification: dict[str, object]) -> list[dict[str, object]]:
    """返回分类明细列表，兼容旧版日志类型字典以支持 TXT 导出。"""
    details = classification.get("classification_details")
    if isinstance(details, list):
        return [detail for detail in details if isinstance(detail, dict)]
    legacy_details = []
    for type_name, info in classification.items():
        if type_name in {"status", "error", "analysis"} or not isinstance(info, dict):
            continue
        legacy_details.append({"logtype": type_name, **info})
    return legacy_details


def _classification_download_text(classification: dict[str, object]) -> str:
    """生成日志分类 TXT，包含结构化结果和每类原始日志样本。"""
    summary_keys = (
        "status",
        "log_format",
        "feature_field",
        "feature_count",
        "total_valid_lines",
        "covered_lines",
    )
    lines = ["日志分类结果", "=" * 20]
    for key in summary_keys:
        if key in classification:
            lines.append(f"{key}: {classification[key]}")
    for detail in _classification_details(classification):
        lines.extend(["", f"日志类型: {detail.get('logtype', '')}"])
        for key, label in (
            ("count", "匹配数量"),
            ("matched_regex", "匹配规则"),
            ("coverage_pct", "覆盖率"),
        ):
            if detail.get(key) not in (None, ""):
                lines.append(f"{label}: {detail[key]}")
        samples = detail.get("real_samples") or detail.get("samples") or detail.get("sample")
        if samples:
            lines.append("原始日志样本:")
            if isinstance(samples, list):
                lines.extend(f"- {sample}" for sample in samples)
            else:
                lines.append(f"- {samples}")
    return "\n".join(lines)


def _threat_mapping_download_text(mappings: object) -> str:
    """生成威胁映射 TXT 表格。"""
    lines = ["原始值\t映射值\t映射类型"]
    for mapping in mappings:
        lines.append(
            "\t".join(
                (
                    str(mapping.original_value),
                    str(mapping.mapped_value),
                    str(mapping.mapping_type),
                )
            )
        )
    return "\n".join(lines)


async def render_execution_report(execution_report: ExecutionReport) -> None:
    """发送一次步骤汇总；七类产物按类型附表格或下载，复合计划全部进同一条汇总。"""
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
        elif artifact.artifact_type == "threat_mapping":
            # 威胁映射产物落表展示（原始值/映射值/类型），不再只显示「步骤执行成功」。
            rows = [
                {
                    "原始值": mapping.original_value,
                    "映射值": mapping.mapped_value,
                    "类型": mapping.mapping_type,
                }
                for mapping in artifact.mappings
            ]
            elements.extend(create_dataframe_elements(rows))
            elements.append(
                cl.File(
                    name=f"{execution_report.plan_id}_threat_mapping.txt",
                    content=_threat_mapping_download_text(artifact.mappings).encode("utf-8"),
                    mime="text/plain",
                )
            )
        elif artifact.artifact_type == "enum_values":
            # 枚举提取产物落表展示，并附可下载文件，保留旧的「下载行为」。
            rows = [{"枚举值": value} for value in artifact.values]
            elements.extend(create_dataframe_elements(rows))
            elements.append(
                cl.File(
                    name=f"{execution_report.plan_id}_enum_values.txt",
                    content="\n".join(artifact.values).encode("utf-8"),
                    mime="text/plain",
                )
            )
        elif artifact.artifact_type == "log_classification":
            # 日志类型提取产物落表展示（日志类型/特征字段/样本数）。
            rows = _classification_detail_rows(artifact.classification)
            elements.extend(create_dataframe_elements(rows))
            elements.append(
                cl.File(
                    name=f"{execution_report.plan_id}_log_classification.txt",
                    content=_classification_download_text(artifact.classification).encode("utf-8"),
                    mime="text/plain",
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
