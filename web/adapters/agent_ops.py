"""日志解析、枚举提取与威胁映射适配器（Issue #88 拆分自 execution_adapters）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger

from web.plan_executor import ExecutionContext
from contracts.planner_models import (
    EnumExtractStep,
    EnumValuesArtifact,
    FieldMappingStep,
    LogClassificationArtifact,
    LogParseStep,
    StepResult,
    StepSpec,
    ThreatMappingArtifact,
    ThreatMappingRow,
    ThreatMappingStep,
)
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
from web.adapters.field_mapping import FieldMappingAdapter, FieldMappingExecutionPolicy
from web.adapters.shared import (
    REPO_ROOT,
    _failed,
    _needs_input,
    _session_get,
    _session_set,
    _success,
    run_member_stream,
)


logger = get_logger("execution_adapters")


class ProfessionalAgentAdapter:
    """直接调用已选定专业 Agent 或领域 Pipeline，不承担意图理解与界面渲染。"""

    def __init__(
        self,
        team: Any,
        mapping_policy: FieldMappingExecutionPolicy | None = None,
        candidate_retriever: Any | None = None,
        object_map_loader: Any | None = None,
    ) -> None:
        """保存专业 Agent 注册表、字段映射执行策略与可注入依赖（Issue #88 接缝）。"""
        self._team = team
        self._mapping_policy = mapping_policy or FieldMappingExecutionPolicy()
        self._field_mapping_adapter = FieldMappingAdapter(
            team,
            mapping_policy,
            candidate_retriever=candidate_retriever,
            object_map_loader=object_map_loader,
        )

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行日志、枚举、字段或威胁操作，并返回类型化产物。"""
        if isinstance(step, LogParseStep):
            return await self._execute_log_parse(step, context)
        if isinstance(step, EnumExtractStep):
            return await self._execute_enum_extract(step, context)
        if isinstance(step, FieldMappingStep):
            return await self._field_mapping_adapter.execute(step, context, dependencies)
        if isinstance(step, ThreatMappingStep):
            return await self._execute_threat_mapping(step, context, dependencies)
        raise TypeError(f"ProfessionalAgentAdapter 不支持步骤类型: {step.type}")

    async def _execute_log_parse(self, step: LogParseStep, context: ExecutionContext) -> StepResult:
        """调用无界面日志 Pipeline，并将分类结果写入当前 session。"""
        from agent.tools import classify_log_features_headless, identify_log_format_headless
        from agent.tools.pipeline.log_sample_filler import fill_sample_logs
        from web.utils import parse_json_safe

        log_lines = _session_get(context.session, "raw_log_lines") or _session_get(
            context.session, "original_log"
        )
        logs_text = "\n".join(str(line) for line in log_lines)
        format_text = await asyncio.to_thread(identify_log_format_headless, logs_text)
        format_info = parse_json_safe(format_text)
        if not isinstance(format_info, dict):
            return _failed(step, "log_format_invalid", "日志格式识别结果不合法")
        classification_text = await asyncio.to_thread(
            classify_log_features_headless,
            logs_text,
            format_info.get("format", "unknown"),
            format_info.get("format_detail", ""),
            # 用户显式指定的分类特征字段优先于 Step1 自动探测值。
            step.feature_field or format_info.get("feature_field", "log_type"),
            json.dumps(format_info, ensure_ascii=False),
            format_info.get("header_end_marker", ""),
            # 显式字段同时压制 Step 2a 定位器对特征字段的改写或改道。
            feature_field_explicit=step.feature_field is not None,
        )
        classification = parse_json_safe(classification_text)
        if not isinstance(classification, dict) or not classification:
            return _failed(step, "log_parse_failed", "日志类型提取没有生成有效结果")
        classification = fill_sample_logs(classification, logs_text)
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

    async def _execute_enum_extract(self, step: EnumExtractStep, context: ExecutionContext) -> StepResult:
        """为显式字段生成正则并提取枚举；模型输出非法时失败，不使用默认正则。"""
        from agent.tools import call_llm_direct
        from agent.tools.enum_extract_tool import (
            extract_enum_with_field,
            sample_logs,
            validate_and_fix_regex,
            validate_regex_with_stats,
        )
        from web.utils import parse_json_safe

        log_lines = _session_get(context.session, "raw_log_lines") or _session_get(
            context.session, "original_log"
        )
        logs_text = "\n".join(str(line) for line in log_lines)
        sampled_logs = sample_logs(logs_text, sample_size=20)
        llm_input = (
            f"{(REPO_ROOT / 'agent' / 'prompts' / 'enum_extract.md').read_text(encoding='utf-8')}\n\n"
            f"目标字段：{step.target_field}\n"
            f"采样日志：\n{sampled_logs}\n\n"
            "只输出包含 field 和 regex 的 JSON；field 必须等于目标字段。"
        )
        response_text = await asyncio.to_thread(
            call_llm_direct,
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
        _session_set(context.session, "last_enum_extract_result", enum_result)
        _session_set(
            context.session,
            "latest_enum_artifact",
            EnumArtifactSlot(artifact=artifact, source_field=artifact.field),
        )
        return _success(step, artifact)

    async def _execute_threat_mapping(
        self,
        step: ThreatMappingStep,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """只使用显式值或本次依赖的枚举产物调用威胁映射 Agent。"""
        from web.parsers import parse_json_threat_result

        source_field: str | None = None
        if step.source_ref == "user.values":
            values = list(step.values)
        elif step.source_ref == "session.artifacts.enum_values":
            raw_slot = _session_get(context.session, "latest_enum_artifact")
            try:
                slot = (
                    raw_slot
                    if isinstance(raw_slot, EnumArtifactSlot)
                    else EnumArtifactSlot.model_validate(raw_slot)
                )
            except (TypeError, ValueError):
                return _needs_input(
                    step,
                    "artifact_source_unavailable",
                    "最近枚举值产物已不可用，请重新提取枚举值",
                )
            values = list(slot.artifact.values)
            source_field = slot.source_field
        else:
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            artifact = dependency.artifact if dependency else None
            if not isinstance(artifact, EnumValuesArtifact):
                return _failed(step, "dependency_type_mismatch", "依赖产物不是枚举值")
            values = list(artifact.values)
            source_field = artifact.field or None
        model_input = json.dumps({"values": values}, ensure_ascii=False)
        content = await self._run_member("ThreatAgent", model_input)
        mapping_rows = parse_json_threat_result(content)
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射未生成有效结果")
        typed_mappings = tuple(ThreatMappingRow.model_validate(row) for row in mapping_rows)
        artifact = ThreatMappingArtifact(
            mappings=typed_mappings,
            item_count=len(typed_mappings),
            source_field=source_field,
        )
        _session_set(context.session, "last_threat_data", mapping_rows)
        _session_set(
            context.session,
            "latest_threat_artifact",
            ThreatArtifactSlot(artifact=artifact, source_field=source_field),
        )
        return _success(step, artifact)

    async def _run_member(
        self,
        member_name: str,
        model_input: str,
        *,
        plan_id: str = "pending",
        step_id: str = "pending",
        batch_number: int | None = None,
    ) -> Any:
        """消费专业 Agent 事件流，只接收完成事件内容并记录安全 token 计数。"""
        return await run_member_stream(
            self._team,
            member_name,
            model_input,
            plan_id=plan_id,
            step_id=step_id,
            batch_number=batch_number,
        )
