"""类型化日志解析适配器：格式识别、分类、样本回填与会话提交。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping

from application.adapters.shared import _failed, _session_get, _session_set, _success
from application.execution import ExecutionContext
from application.parsing import parse_json_safe
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

        log_lines = _session_get(context.session, "raw_log_lines") or _session_get(
            context.session, "original_log"
        )
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

        classification = self._sample_filler(classification, logs_text)
        _session_set(context.session, "log_classification", classification)
        classification_details = classification.get("classification_details")
        item_count = (
            len(classification_details)
            if isinstance(classification_details, list)
            else len(classification)
        )
        return _success(
            step,
            LogClassificationArtifact(
                classification=classification,
                item_count=item_count,
            ),
        )
