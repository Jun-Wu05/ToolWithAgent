"""类型化日志解析适配器：格式识别、分类、样本回填与会话提交。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping

from application.adapters.shared import _failed, _success
from application.execution import ExecutionContext
from application.parsing import parse_json_safe
from application.log_knowledge_submission import build_submission_snapshot
from application.session_state import commit_log_classification
from contracts.planner_models import (
    LogClassificationArtifact,
    LogParseStep,
    StepResult,
    StepSpec,
)


FormatIdentifier = Callable[[str], str]
Classifier = Callable[..., str]
SampleFiller = Callable[[dict, str], dict]


def _identify_log_format(logs_text: str) -> str:
    """延迟进入 Agent 门面，避免 Application 导入时加载具体模型实现。"""
    from agent.tools import identify_log_format_headless

    return identify_log_format_headless(logs_text)


def _classify_log_features(*args, **kwargs) -> str:
    """延迟调用现有日志分类 Pipeline，保持测试替身的绑定时机。"""
    from agent.tools import classify_log_features_headless

    return classify_log_features_headless(*args, **kwargs)


def _fill_log_samples(classification: dict, logs_text: str) -> dict:
    """经 Agent 公开门面回填真实样本，不跨包引用私有实现。"""
    from agent.tools import fill_log_samples

    return fill_log_samples(classification, logs_text)


class LogParseAdapter:
    """执行单个日志解析步骤，不理解用户原文或承担界面渲染。"""

    def __init__(
        self,
        *,
        format_identifier: FormatIdentifier | None = None,
        classifier: Classifier | None = None,
        sample_filler: SampleFiller | None = None,
    ) -> None:
        """允许测试在同一接缝注入计数假件，生产默认延迟进入 Agent。"""
        self._format_identifier = format_identifier or _identify_log_format
        self._classifier = classifier or _classify_log_features
        self._sample_filler = sample_filler or _fill_log_samples

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """按冻结顺序识别格式、分类、回填样本并一次性提交会话。"""
        if not isinstance(step, LogParseStep):
            raise TypeError("LogParseAdapter 只接受 LogParseStep")

        log_lines = context.session.raw_log_lines or context.session.original_log
        logs_text = "\n".join(str(line) for line in log_lines)
        format_text = await asyncio.to_thread(self._format_identifier, logs_text)
        format_info = parse_json_safe(format_text)
        if not isinstance(format_info, dict):
            return _failed(step, "log_format_invalid", "日志格式识别结果不合法")

        classification_text = await asyncio.to_thread(
            self._classifier,
            logs_text,
            format_info.get("format", "unknown"),
            format_info.get("format_detail", ""),
            step.feature_field or format_info.get("feature_field", "log_type"),
            json.dumps(format_info, ensure_ascii=False),
            format_info.get("header_end_marker", ""),
            feature_field_explicit=step.feature_field is not None,
        )
        classification = parse_json_safe(classification_text)
        if not isinstance(classification, dict) or not classification:
            return _failed(step, "log_parse_failed", "日志类型提取没有生成有效结果")
        if classification.get("status") == "UNSUPPORTED":
            # 数据不属于 KV/JSON 范畴：明确告知判定结果而不是伪成功
            # （#298：此前 UNSUPPORTED 走 _success，界面显示"步骤执行成功"
            # + 空结果表 + 后续操作按钮）。错误码不进重试白名单——格式
            # 判定是数据本身的确定性属性，计划级重跑不会改变结论。
            fmt = str(format_info.get("format") or "unknown")
            fmt_detail = str(format_info.get("format_detail") or "") or fmt
            return _failed(
                step,
                "log_format_unsupported",
                f"日志格式识别为「{fmt_detail}」（{fmt}），"
                "不属于支持的 KV/JSON 范畴，无法进行日志类型提取",
            )

        if classification.get("status") != "SUCCESS":
            # 仅完整成功可发布；失败或部分结果保持上一次正式分类不变。
            # 分类器失败原因在 fail_reason（#433 前误取 error，导致永远显示笼统文案）。
            reason = (
                classification.get("fail_reason")
                or classification.get("error")
                or "分类器未提供失败原因"
            )
            return _failed(step, "log_parse_failed", f"日志类型提取失败：{reason}")
        classification = self._sample_filler(classification, logs_text)
        submission = build_submission_snapshot(
            classification,
            log_lines,
            selection_mode="explicit" if step.feature_field is not None else "automatic",
            feature_field=step.feature_field,
        )
        cleared_mapping_derivatives = commit_log_classification(
            context.session, classification, submission
        )
        classification_details = classification.get("classification_details")
        item_count = (
            len(classification_details)
            if isinstance(classification_details, list)
            else len(classification)
        )
        message = None
        if cleared_mapping_derivatives:
            message = (
                "日志类型提取完成；⚠️ 已清除上一轮字段映射、事件标注和手动调整，"
                "如需完整版子规则请重新执行字段映射"
            )
        return _success(
            step,
            LogClassificationArtifact(
                classification=classification,
                item_count=item_count,
                submission_eligible=submission.eligible,
                submission_token=(
                    submission.submission_token if submission.eligible else None
                ),
            ),
            message=message,
        )
