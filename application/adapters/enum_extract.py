"""枚举提取适配器：生成正则、验证、全量提取并提交类型化产物。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Callable

from application.adapters.shared import _failed, _success
from application.execution import ExecutionContext
from application.parsing import parse_json_safe
from contracts.planner_models import (
    EnumExtractStep,
    EnumValuesArtifact,
    StepResult,
    StepSpec,
)
from contracts.session_artifacts import EnumArtifactSlot


class EnumExtractAdapter:
    """在小接口后隐藏枚举正则生成、校验、修复与全量提取顺序。"""

    def __init__(
        self,
        *,
        llm_caller: Callable[..., Any] | None = None,
        prompt_loader: Callable[[], str] | None = None,
    ) -> None:
        """保存可计数的模型调用与 Prompt 加载接缝。"""
        if llm_caller is None:
            from agent.tools import call_llm_direct
            llm_caller = call_llm_direct
        if prompt_loader is None:
            from agent.prompts import load_enum_extract_prompt
            prompt_loader = load_enum_extract_prompt
        self._llm_caller = llm_caller
        self._prompt_loader = prompt_loader

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """为显式字段生成正则并提取枚举，失败时不读取或覆盖旧结果。"""
        if not isinstance(step, EnumExtractStep):
            raise TypeError("EnumExtractAdapter 只接受 EnumExtractStep")
        from agent.tools.enum_extract_tool import (
            extract_enum_with_field,
            sample_logs,
            validate_and_fix_regex,
            validate_regex_with_stats,
        )

        log_lines = context.session.raw_log_lines or context.session.original_log
        logs_text = "\n".join(str(line) for line in log_lines)
        sampled_logs = sample_logs(logs_text, sample_size=20)
        llm_input = (
            f"{self._prompt_loader()}\n\n"
            f"目标字段：{step.target_field}\n"
            f"采样日志：\n{sampled_logs}\n\n"
            "只输出包含 field 和 regex 的 JSON；field 必须等于目标字段。"
        )
        response_text = await asyncio.to_thread(
            self._llm_caller,
            llm_input,
            temperature=0.1,
            max_tokens=500,
            timeout=120,
        )
        regex_data = parse_json_safe(response_text)
        if not isinstance(regex_data, dict):
            return _failed(step, "enum_regex_invalid", "枚举正则生成结果不是合法 JSON")
        if regex_data.get("field") != step.target_field or not regex_data.get("regex"):
            return _failed(step, "enum_regex_invalid", "枚举正则结果缺少明确字段或正则")
        regex = str(regex_data["regex"])
        validation = validate_regex_with_stats(regex, sampled_logs)
        if not validation.get("valid"):
            fixed = validate_and_fix_regex(regex, sampled_logs, step.target_field)
            if not fixed.get("valid"):
                return _failed(step, "enum_regex_no_match", "生成的正则无法匹配目标字段")
            regex = str(fixed["regex"])
        enum_result = extract_enum_with_field(logs_text, step.target_field, regex)
        values = enum_result.get("value", []) if isinstance(enum_result, dict) else []
        if not values:
            return _failed(step, "enum_extract_empty", "未提取到枚举值")
        artifact = EnumValuesArtifact(
            values=tuple(str(value) for value in values),
            item_count=len(values),
            field=str(enum_result.get("field") or step.target_field),
            regex=str(enum_result.get("regex") or regex),
            original_log=tuple(str(line) for line in enum_result.get("original_log", [])),
        )
        context.session.last_enum_extract_result = enum_result
        context.session.latest_enum_artifact = EnumArtifactSlot(
            artifact=artifact, source_field=artifact.field
        )
        return _success(step, artifact)


__all__ = ["EnumExtractAdapter"]
