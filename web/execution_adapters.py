"""把类型化步骤连接到领域函数和无界面专业执行器。"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import inspect
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.shared.logger import get_logger

from agent.shared.mapping_utils import (
    apply_fill_to_config,
    count_field_mappings,
    remove_field_mappings_from_config,
)
from web.plan_executor import ExecutionContext, StepAdapter
from web.progress import ProgressEvent, ProgressPhase, ProgressStatus
from web.planner_models import (
    ConfigExportArtifact,
    EnumExtractStep,
    EnumValuesArtifact,
    ExportStep,
    FieldMappingArtifact,
    FieldMappingRow,
    FieldMappingStep,
    FillStep,
    LogClassificationArtifact,
    LogParseStep,
    RemoveMappingStep,
    StepArtifact,
    StepResult,
    StepSpec,
    StepStatus,
    ThreatMappingArtifact,
    ThreatMappingRow,
    ThreatMappingStep,
)


logger = get_logger("execution_adapters")

@dataclass(frozen=True)
class FieldMappingExecutionPolicy:
    """定义字段映射批处理的并发、超时和重试边界。"""

    batch_size: int = 25
    max_concurrency: int = 3
    timeout_seconds: float = 90.0
    max_retries: int = 1
    retry_delay_seconds: float = 2.0
    backfill_max_attempts: int = 2


class FieldMappingBatchError(RuntimeError):
    """描述可定位到具体批次的字段映射失败。"""

    def __init__(self, batch_number: int, error_code: str, message: str) -> None:
        """保存批次、稳定错误码和安全错误消息。"""
        super().__init__(message)
        self.batch_number = batch_number
        self.error_code = error_code


def _model_error_status_code(error: Exception) -> int | None:
    """从常见 SDK 异常中读取 HTTP 状态码，不依赖具体供应商类型。"""
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        return int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        return None


def _is_retriable_model_error(error: Exception) -> bool:
    """仅允许瞬时网络、限流、服务端和超时错误重试一次。"""
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    error_type = type(error).__name__
    if error_type in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "RateLimitError",
    }:
        return True
    status_code = _model_error_status_code(error)
    return status_code == 429 or (status_code is not None and status_code >= 500)


def _retry_delay_seconds(error: Exception, default_seconds: float) -> float:
    """优先采用 Retry-After，且将服务端等待建议限制在十秒内。"""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        return min(max(float(retry_after), 0.0), 10.0)
    except (TypeError, ValueError):
        return default_seconds


async def _publish_progress(
    context: ExecutionContext,
    step: StepSpec,
    phase: ProgressPhase,
    status: ProgressStatus,
    message_code: str,
    *,
    current_batch: int | None = None,
    total_batches: int | None = None,
    elapsed_seconds: float = 0.0,
) -> None:
    """向执行上下文发布不含原始输入值的安全进度事件。"""
    await context.progress_sink.publish(
        ProgressEvent(
            plan_id=context.plan_id,
            step_id=step.step_id,
            phase=phase,
            status=status,
            message_code=message_code,
            current_batch=current_batch,
            total_batches=total_batches,
            elapsed_seconds=elapsed_seconds,
        )
    )

def _session_get(session: Any, key: str, default: Any = None) -> Any:
    """在迁移期集中兼容 SessionState 与字典，适配器外不传播裸 key 判断。"""
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _session_set(session: Any, key: str, value: Any) -> None:
    """集中写入会话字段，并在未知字段时立即失败。"""
    if isinstance(session, dict):
        session[key] = value
        return
    setattr(session, key, value)


_CONFIG_SESSION_KEYS = {
    "session.decoded_config": "decoded_data",
    "session.mapped_sub_rules": "mapped_sub_rules",
}


def _read_config(session: Any, config_ref: str) -> Any:
    """按显式配置引用读取 session，未知引用立即失败且不尝试其他来源。"""
    session_key = _CONFIG_SESSION_KEYS.get(config_ref)
    if session_key is None:
        raise ValueError(f"不支持的配置来源: {config_ref}")
    return _session_get(session, session_key)


def _write_config(session: Any, config_ref: str, config: Any) -> None:
    """把更新结果写回原配置来源，禁止在两个 session 字段之间隐式迁移。"""
    session_key = _CONFIG_SESSION_KEYS.get(config_ref)
    if session_key is None:
        raise ValueError(f"不支持的配置来源: {config_ref}")
    _session_set(session, session_key, config)

def _enum_mapping_table(
    enum_preview: list[dict[str, Any]],
    target_fields: tuple[str, ...],
) -> dict[str, list[dict[str, str]]]:
    """从已解析预览构建映射表，避免执行阶段重新依赖真实 Excel 路径。"""
    targets = set(target_fields)
    table: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in enum_preview:
        target_field = str(row.get("目标字段", "")).strip()
        if target_field not in targets:
            continue
        original_value = row.get("orgValue", row.get("原始值", ""))
        mapped_value = row.get("mappingValue", row.get("映射值", original_value))
        table[target_field].append(
            {
                "mappingType": str(row.get("mappingType", "EQUAL")),
                "orgValue": str(original_value),
                "mappingValue": str(mapped_value),
            }
        )
    return dict(table)


def _build_config_artifact(updated_config: Any, item_count: int) -> ConfigExportArtifact:
    """把完整配置编码为统一下载产物，不改变根对象类型。"""
    encoded_config = base64.b64encode(
        json.dumps(updated_config, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return ConfigExportArtifact(content=encoded_config, item_count=item_count)

class EnumFillAdapter:
    """以显式目标字段和配置来源执行枚举填充。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行枚举填充；任一来源缺失时快速失败且不读取其他配置兜底。"""
        if not isinstance(step, FillStep) or step.fill_kind != "enum":
            raise TypeError("EnumFillAdapter 只接受 enum FillStep")
        current_config = _read_config(context.session, step.config_ref)
        enum_preview = _session_get(context.session, "enum_preview") or []
        mapping_table = _enum_mapping_table(enum_preview, step.target_fields)
        if not mapping_table:
            return _needs_input(step, "enum_mapping_required", "当前枚举映射表没有可用于目标字段的规则")

        before_count = count_field_mappings(current_config, step.target_fields)
        updated_config = apply_fill_to_config(current_config, mapping_table)
        after_count = count_field_mappings(updated_config, step.target_fields)
        _write_config(context.session, step.config_ref, updated_config)
        logger.info(
            "[ENUM_FILL] 填充完成: step_id=%s config_ref=%s target_field_count=%s "
            "mapping_rule_count=%s before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            sum(len(items) for items in mapping_table.values()),
            before_count,
            after_count,
            max(0, after_count - before_count),
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=max(0, after_count - before_count),
            artifact=_build_config_artifact(updated_config, after_count),
            message="枚举映射已填充到目标字段",
        )

class ThreatFillAdapter:
    """只消费本次声明的威胁映射产物并填充显式配置来源。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行威胁填充；依赖或配置来源不匹配时快速失败。"""
        if not isinstance(step, FillStep) or step.fill_kind != "threat":
            raise TypeError("ThreatFillAdapter 只接受 threat FillStep")
        dependency_id = step.source_ref.removeprefix("step:")
        dependency = dependencies.get(dependency_id)
        if dependency is None or dependency.artifact is None:
            return _failed(step, "dependency_missing", "威胁填充缺少声明的映射产物")
        if not isinstance(dependency.artifact, ThreatMappingArtifact):
            return _failed(step, "dependency_type_mismatch", "依赖产物不是威胁映射")
        mapping_rows = [row.model_dump(by_alias=True) for row in dependency.artifact.mappings]
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射产物为空")

        current_config = _read_config(context.session, step.config_ref)
        before_count = count_field_mappings(current_config, step.target_fields)
        updated_config = current_config
        for target_field in step.target_fields:
            updated_config = apply_fill_to_config(updated_config, mapping_rows, target_field)
        after_count = count_field_mappings(updated_config, step.target_fields)
        _write_config(context.session, step.config_ref, updated_config)
        logger.info(
            "[THREAT_FILL] 填充完成: step_id=%s config_ref=%s target_field_count=%s "
            "mapping_rule_count=%s before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            len(mapping_rows),
            before_count,
            after_count,
            max(0, after_count - before_count),
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=max(0, after_count - before_count),
            artifact=_build_config_artifact(updated_config, after_count),
            message="威胁映射已填充到目标字段",
        )

class FillAdapter:
    """按类型化 fill_kind 委派填充实现，不从文本或 session 猜测类型。"""

    def __init__(self) -> None:
        """创建两种明确的填充实现。"""
        self._enum_adapter = EnumFillAdapter()
        self._threat_adapter = ThreatFillAdapter()

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """仅根据 FillStep.fill_kind 分派，未知类型由 Pydantic 在更早阶段拒绝。"""
        if not isinstance(step, FillStep):
            raise TypeError("FillAdapter 只接受 FillStep")
        if step.fill_kind == "enum":
            return await self._enum_adapter.execute(step, context, dependencies)
        return await self._threat_adapter.execute(step, context, dependencies)


class RemoveMappingAdapter:
    """清除显式配置来源中目标字段的 mappings，并导出完整配置。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行取消映射；没有实际清除时返回待输入，禁止静默成功。"""
        if not isinstance(step, RemoveMappingStep):
            raise TypeError("RemoveMappingAdapter 只接受 RemoveMappingStep")
        current_config = _read_config(context.session, step.config_ref)
        before_count = count_field_mappings(current_config, step.target_fields)
        updated_config = current_config
        for target_field in step.target_fields:
            updated_config = remove_field_mappings_from_config(updated_config, target_field)
        after_count = count_field_mappings(updated_config, step.target_fields)
        if before_count == after_count:
            return _needs_input(step, "mapping_not_found", "目标字段没有可取消的映射")
        _write_config(context.session, step.config_ref, updated_config)
        logger.info(
            "[REMOVE_MAPPING] 取消完成: step_id=%s config_ref=%s target_field_count=%s "
            "before_count=%s after_count=%s changed_count=%s",
            step.step_id,
            step.config_ref,
            len(step.target_fields),
            before_count,
            after_count,
            before_count - after_count,
        )
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            changed_count=before_count - after_count,
            artifact=_build_config_artifact(updated_config, after_count),
            message="目标字段映射已取消",
        )

class ExportAdapter:
    """导出当前明确来源的配置，不改变 session 状态。"""

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """导出 session 领域结果或声明依赖的配置产物。"""
        if not isinstance(step, ExportStep):
            raise TypeError("ExportAdapter 只接受 ExportStep")

        if step.source_ref.startswith("step:"):
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            artifact = dependency.artifact if dependency else None
            if not isinstance(artifact, ConfigExportArtifact):
                return _failed(step, "dependency_type_mismatch", "声明的依赖没有配置产物")
            exported_text = artifact.content
            exported_item_count = artifact.item_count
        elif step.source_ref in _CONFIG_SESSION_KEYS:
            current_config = _read_config(context.session, step.source_ref)
            if not current_config:
                return _needs_input(step, "export_source_required", "当前没有可导出的配置")
            exported_item_count = len(current_config) if isinstance(current_config, list) else 1
            exported_text = _build_config_artifact(current_config, exported_item_count).content
        else:
            from agent.tools.rule_generator import generate_rules, rules_to_base64_text

            classification = _session_get(context.session, "log_classification")
            if not isinstance(classification, dict) or not classification:
                return _needs_input(step, "log_classification_required", "请先完成日志类型提取")
            export_mode = (
                "entry"
                if step.source_ref == "session.log_classification.entry_rules"
                else "sub"
            )
            generated_rules = generate_rules(classification, mode=export_mode)
            if not generated_rules.get("success"):
                return _failed(step, "rule_export_failed", "规则生成失败")
            rules = generated_rules.get("rules", [])
            exported_text = rules_to_base64_text(rules)
            exported_item_count = len(rules)

        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.SUCCESS,
            artifact=ConfigExportArtifact(
                content=exported_text,
                item_count=exported_item_count,
            ),
            message="配置已导出",
        )

class ProfessionalAgentAdapter:
    """直接调用已选定专业 Agent 或领域 Pipeline，不承担意图理解与界面渲染。"""

    def __init__(
        self,
        team: Any,
        mapping_policy: FieldMappingExecutionPolicy | None = None,
    ) -> None:
        """保存专业 Agent 注册表和字段映射执行策略。"""
        self._team = team
        self._mapping_policy = mapping_policy or FieldMappingExecutionPolicy()

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
            return await self._execute_field_mapping(step, context)
        if isinstance(step, ThreatMappingStep):
            return await self._execute_threat_mapping(step, context, dependencies)
        raise TypeError(f"ProfessionalAgentAdapter 不支持步骤类型: {step.type}")

    async def _execute_log_parse(self, step: LogParseStep, context: ExecutionContext) -> StepResult:
        """调用无界面日志 Pipeline，并将分类结果写入当前 session。"""
        from agent.tools.log_parser_pipeline import (
            _do_classify_log_features,
            _do_identify_log_format,
            fill_sample_logs,
        )
        from web.utils import parse_json_safe

        log_lines = _session_get(context.session, "raw_log_lines") or _session_get(
            context.session, "original_log"
        )
        logs_text = "\n".join(str(line) for line in log_lines)
        format_text = await asyncio.to_thread(_do_identify_log_format, logs_text)
        format_info = parse_json_safe(format_text)
        if not isinstance(format_info, dict):
            return _failed(step, "log_format_invalid", "日志格式识别结果不合法")
        classification_text = await asyncio.to_thread(
            _do_classify_log_features,
            logs_text,
            format_info.get("format", "unknown"),
            format_info.get("format_detail", ""),
            format_info.get("feature_field", "log_type"),
            json.dumps(format_info, ensure_ascii=False),
            format_info.get("header_end_marker", ""),
        )
        classification = parse_json_safe(classification_text)
        if not isinstance(classification, dict) or not classification:
            return _failed(step, "log_parse_failed", "日志类型提取没有生成有效结果")
        classification = fill_sample_logs(classification, logs_text)
        _session_set(context.session, "log_classification", classification)
        return _success(
            step,
            LogClassificationArtifact(
                classification=classification,
                item_count=len(classification),
            ),
        )

    async def _execute_enum_extract(self, step: EnumExtractStep, context: ExecutionContext) -> StepResult:
        """为显式字段生成正则并提取枚举；模型输出非法时失败，不使用默认正则。"""
        from agent.tools.enum_extract_tool import (
            extract_enum_with_field,
            sample_logs,
            validate_and_fix_regex,
            validate_regex_with_stats,
        )
        from agent.tools.pipeline.llm_client import _call_llm_direct
        from web.utils import parse_json_safe

        log_lines = _session_get(context.session, "raw_log_lines") or _session_get(
            context.session, "original_log"
        )
        logs_text = "\n".join(str(line) for line in log_lines)
        sampled_logs = sample_logs(logs_text, sample_size=20)
        llm_input = (
            f"{(Path(__file__).resolve().parent.parent / 'agent' / 'prompts' / 'enum_extract.md').read_text(encoding='utf-8')}\n\n"
            f"目标字段：{step.target_field}\n"
            f"采样日志：\n{sampled_logs}\n\n"
            "只输出包含 field 和 regex 的 JSON；field 必须等于目标字段。"
        )
        response_text = await asyncio.to_thread(
            _call_llm_direct,
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
        _session_set(context.session, "last_enum_extract_result", enum_result)
        return _success(
            step,
            EnumValuesArtifact(values=tuple(str(value) for value in values), item_count=len(values)),
        )

    async def _backfill_field_mapping_rows(
        self,
        batch_rows: list[dict[str, Any]],
        fields_batch: list[str],
        context: ExecutionContext,
        step: FieldMappingStep,
        batch_number: int,
        total_batches: int,
    ) -> list[dict[str, Any]]:
        """补齐模型漏掉的字段，仍缺失则兜底为「未匹配」，避免单字段缺失作废整步。

        模型在 25 字段大 batch 上常漏 1～2 个字段（如线上 24/25）。这里先按字段名
        去重归集、忽略批次外字段，再对缺失字段单独补查（重试 backfill_max_attempts
        次），最后仍缺的标记「未匹配」。返回值严格按 fields_batch 顺序、数量一致，
        原始字段名归一为输入名，顺带消除了旧校验对返回顺序的敏感。
        """
        from web.input_builder import build_batch_llm_input
        from web.parsers import parse_json_mapping_result

        policy = self._mapping_policy
        fields_set = set(fields_batch)

        # 按字段名归集模型返回；键以 strip 后比对以容忍首尾空白漂移。
        covered: dict[str, dict[str, Any]] = {}
        duplicate_count = 0
        extra_count = 0
        for row in batch_rows:
            name = str(row.get("原始字段名", "")).strip()
            if not name:
                continue
            if name not in fields_set:
                extra_count += 1
                continue
            if name in covered:
                duplicate_count += 1
                continue
            covered[name] = row

        missing = [field for field in fields_batch if field not in covered]
        for attempt in range(policy.backfill_max_attempts):
            if not missing:
                break
            logger.info(
                "[BATCH_BACKFILL] 补查缺失字段: plan_id=%s step_id=%s batch=%s/%s "
                "attempt=%s missing_count=%s",
                context.plan_id,
                step.step_id,
                batch_number,
                total_batches,
                attempt + 1,
                len(missing),
            )
            try:
                backfill_input = await asyncio.to_thread(
                    build_batch_llm_input,
                    "补查标准字段映射",
                    context.session,
                    missing,
                    batch_number,
                    total_batches,
                )
                content = await asyncio.wait_for(
                    self._run_member(
                        "FieldMappingAgent",
                        backfill_input,
                        plan_id=context.plan_id,
                        step_id=step.step_id,
                        batch_number=batch_number,
                    ),
                    timeout=policy.timeout_seconds,
                )
            except Exception as error:
                logger.warning(
                    "[BATCH_BACKFILL] 补查调用失败，停止补查并兜底未匹配: "
                    "plan_id=%s step_id=%s batch=%s/%s error_category=%s remaining_count=%s",
                    context.plan_id,
                    step.step_id,
                    batch_number,
                    total_batches,
                    type(error).__name__,
                    len(missing),
                )
                break
            for row in parse_json_mapping_result(content):
                name = str(row.get("原始字段名", "")).strip()
                if not name or name not in fields_set or name in covered:
                    continue
                covered[name] = row
            missing = [field for field in fields_batch if field not in covered]

        # 仍缺失的字段兜底为「未匹配」，保证每个输入字段都有结果，避免整步作废。
        fallback_count = 0
        for field in missing:
            covered[field] = {
                "原始字段名": field,
                "系统属性名称": "未匹配",
                "匹配状态": "未匹配",
            }
            fallback_count += 1

        if duplicate_count or extra_count or fallback_count:
            logger.warning(
                "[BATCH_NORMALIZED] 批次结果归一化: plan_id=%s step_id=%s batch=%s/%s "
                "duplicate_count=%s extra_count=%s fallback_count=%s",
                context.plan_id,
                step.step_id,
                batch_number,
                total_batches,
                duplicate_count,
                extra_count,
                fallback_count,
            )

        # 按 fields_batch 顺序输出，原始字段名归一为输入名，保证下游顺序与数量一致。
        return [{**covered[field], "原始字段名": field} for field in fields_batch]

    async def _execute_field_mapping(
        self,
        step: FieldMappingStep,
        context: ExecutionContext,
    ) -> StepResult:
        """并发执行字段映射批次，并在全部校验成功后一次性写回 session。"""
        from web.input_builder import build_batch_llm_input
        from web.parsers import parse_json_mapping_result

        available_fields = list(context.session_facts.available_fields)
        policy = self._mapping_policy
        total_batches = (len(available_fields) + policy.batch_size - 1) // policy.batch_size
        semaphore = asyncio.Semaphore(policy.max_concurrency)

        async def execute_batch(batch_index: int) -> tuple[int, list[dict[str, Any]]]:
            """执行一个受并发限制的批次，并返回经过字段集合校验的映射。"""
            fields_batch = available_fields[
                batch_index * policy.batch_size : (batch_index + 1) * policy.batch_size
            ]
            batch_number = batch_index + 1
            async with semaphore:
                batch_started_at = time.monotonic()
                await _publish_progress(
                    context,
                    step,
                    ProgressPhase.RETRIEVAL,
                    ProgressStatus.RUNNING,
                    "field_candidates_retrieving",
                    current_batch=batch_number,
                    total_batches=total_batches,
                )
                logger.info(
                    "[BATCH_START] 字段映射批次开始: plan_id=%s step_id=%s "
                    "batch=%s/%s field_count=%s",
                    context.plan_id,
                    step.step_id,
                    batch_number,
                    total_batches,
                    len(fields_batch),
                )
                retrieval_started_at = time.monotonic()
                logger.info(
                    "[MODEL_CALL_START] Embedding 调用开始: plan_id=%s step_id=%s "
                    "batch=%s/%s model=%s field_count=%s timeout_seconds=%s",
                    context.plan_id,
                    step.step_id,
                    batch_number,
                    total_batches,
                    "Qwen/Qwen3-Embedding-8B",
                    len(fields_batch),
                    30,
                )
                try:
                    model_input = await asyncio.to_thread(
                        build_batch_llm_input,
                        "执行标准字段映射",
                        context.session,
                        fields_batch,
                        batch_number,
                        total_batches,
                    )
                except Exception as error:
                    retrieval_elapsed = time.monotonic() - retrieval_started_at
                    logger.warning(
                        "[MODEL_CALL_FAILED] Embedding 调用失败: plan_id=%s step_id=%s "
                        "batch=%s/%s elapsed_seconds=%.3f error_category=%s",
                        context.plan_id,
                        step.step_id,
                        batch_number,
                        total_batches,
                        retrieval_elapsed,
                        type(error).__name__,
                    )
                    await _publish_progress(
                        context,
                        step,
                        ProgressPhase.RETRIEVAL,
                        ProgressStatus.FAILED,
                        "field_candidates_failed",
                        current_batch=batch_number,
                        total_batches=total_batches,
                        elapsed_seconds=retrieval_elapsed,
                    )
                    raise FieldMappingBatchError(
                        batch_number,
                        "field_retrieval_failed",
                        f"第 {batch_number} 批字段候选检索失败",
                    ) from error
                retrieval_elapsed = time.monotonic() - retrieval_started_at
                logger.info(
                    "[MODEL_CALL_END] Embedding 调用完成: plan_id=%s step_id=%s "
                    "batch=%s/%s elapsed_seconds=%.3f field_count=%s",
                    context.plan_id,
                    step.step_id,
                    batch_number,
                    total_batches,
                    retrieval_elapsed,
                    len(fields_batch),
                )
                await _publish_progress(
                    context,
                    step,
                    ProgressPhase.RETRIEVAL,
                    ProgressStatus.SUCCESS,
                    "field_candidates_ready",
                    current_batch=batch_number,
                    total_batches=total_batches,
                    elapsed_seconds=retrieval_elapsed,
                )
                for attempt in range(policy.max_retries + 1):
                    try:
                        model_started_at = time.monotonic()
                        await _publish_progress(
                            context,
                            step,
                            ProgressPhase.MODEL_CALL,
                            ProgressStatus.RUNNING,
                            "field_mapping_batch_running",
                            current_batch=batch_number,
                            total_batches=total_batches,
                        )
                        logger.info(
                            "[MODEL_CALL_START] 专业模型调用开始: plan_id=%s step_id=%s operation=field_mapping "
                            "batch=%s/%s attempt=%s model_input_length=%s",
                            context.plan_id,
                            step.step_id,
                            batch_number,
                            total_batches,
                            attempt + 1,
                            len(model_input),
                        )
                        content = await asyncio.wait_for(
                            self._run_member(
                                "FieldMappingAgent",
                                model_input,
                                plan_id=context.plan_id,
                                step_id=step.step_id,
                                batch_number=batch_number,
                            ),
                            timeout=policy.timeout_seconds,
                        )
                        logger.info(
                            "[MODEL_CALL_END] 专业模型调用完成: plan_id=%s step_id=%s operation=field_mapping "
                            "batch=%s/%s attempt=%s elapsed_seconds=%.3f",
                            context.plan_id,
                            step.step_id,
                            batch_number,
                            total_batches,
                            attempt + 1,
                            time.monotonic() - model_started_at,
                        )
                        await _publish_progress(
                            context,
                            step,
                            ProgressPhase.MODEL_CALL,
                            ProgressStatus.SUCCESS,
                            "field_mapping_batch_completed",
                            current_batch=batch_number,
                            total_batches=total_batches,
                            elapsed_seconds=time.monotonic() - model_started_at,
                        )
                        batch_rows = parse_json_mapping_result(content)
                        batch_rows = await self._backfill_field_mapping_rows(
                            batch_rows,
                            fields_batch,
                            context,
                            step,
                            batch_number,
                            total_batches,
                        )
                        logger.info(
                            "[BATCH_END] 字段映射批次完成: plan_id=%s step_id=%s batch=%s/%s "
                            "field_count=%s elapsed_seconds=%.3f",
                            context.plan_id,
                            step.step_id,
                            batch_number,
                            total_batches,
                            len(batch_rows),
                            time.monotonic() - batch_started_at,
                        )
                        return batch_index, batch_rows
                    except FieldMappingBatchError:
                        raise
                    except asyncio.TimeoutError as error:
                        error_code = "field_mapping_timeout"
                        logger.warning(
                            "[MODEL_CALL_TIMEOUT] 专业模型调用超时: plan_id=%s step_id=%s operation=field_mapping "
                            "batch=%s/%s attempt=%s timeout_seconds=%s",
                            context.plan_id,
                            step.step_id,
                            batch_number,
                            total_batches,
                            attempt + 1,
                            policy.timeout_seconds,
                        )
                        last_error = error
                        retriable = True
                    except Exception as error:
                        error_code = "field_mapping_model_failed"
                        logger.warning(
                            "[MODEL_CALL_FAILED] 专业模型调用失败: plan_id=%s step_id=%s operation=field_mapping "
                            "batch=%s/%s attempt=%s error_category=%s",
                            context.plan_id,
                            step.step_id,
                            batch_number,
                            total_batches,
                            attempt + 1,
                            type(error).__name__,
                        )
                        last_error = error
                        retriable = _is_retriable_model_error(error)
                    if retriable and attempt < policy.max_retries:
                        retry_delay = _retry_delay_seconds(last_error, policy.retry_delay_seconds)
                        logger.info(
                            "[BATCH_RETRY] 字段映射批次重试: plan_id=%s step_id=%s batch=%s/%s "
                            "next_attempt=%s delay_seconds=%s",
                            context.plan_id,
                            step.step_id,
                            batch_number,
                            total_batches,
                            attempt + 2,
                            retry_delay,
                        )
                        await _publish_progress(
                            context,
                            step,
                            ProgressPhase.MODEL_CALL,
                            ProgressStatus.RUNNING,
                            "field_mapping_batch_retry",
                            current_batch=batch_number,
                            total_batches=total_batches,
                        )
                        await asyncio.sleep(retry_delay)
                    else:
                        break
                raise FieldMappingBatchError(
                    batch_number,
                    error_code,
                    f"第 {batch_number} 批字段映射失败: {type(last_error).__name__}",
                )

        tasks = [
            asyncio.create_task(execute_batch(batch_index))
            for batch_index in range(total_batches)
        ]
        try:
            completed_batches = await asyncio.gather(*tasks)
        except FieldMappingBatchError as error:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.error(
                "[BATCH_FAILED] 字段映射原子失败: plan_id=%s step_id=%s batch=%s/%s error_category=%s",
                context.plan_id,
                step.step_id,
                error.batch_number,
                total_batches,
                error.error_code,
            )
            return _failed(step, error.error_code, str(error))

        await _publish_progress(
            context,
            step,
            ProgressPhase.VALIDATION,
            ProgressStatus.RUNNING,
            "field_mapping_validating",
        )
        mapping_rows = [
            row
            for _, batch_rows in sorted(completed_batches, key=lambda item: item[0])
            for row in batch_rows
        ]
        if len(mapping_rows) != len(available_fields):
            return _failed(step, "field_mapping_incomplete", "字段映射结果数量与输入字段数量不一致")

        typed_mappings = tuple(FieldMappingRow.model_validate(row) for row in mapping_rows)
        staged_sub_rule_results = None
        staged_mapped_sub_rules = None
        # 子规则计算可能抛错或原地修改输入，因此必须在 session 副本上完成后再提交。
        sub_rules = copy.deepcopy(_session_get(context.session, "mapped_sub_rules") or [])
        if not sub_rules:
            classification = _session_get(context.session, "log_classification")
            raw_log_lines = _session_get(context.session, "raw_log_lines", []) or []
            if isinstance(classification, dict) and classification:
                from agent.tools.rule_generator import generate_sub_rules

                logs_text = "\n".join(str(line) for line in raw_log_lines)
                sub_rules = generate_sub_rules(classification, all_logs_str=logs_text)
        if sub_rules:
            from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_sub_rules
            from agent.tools.standard_mapper import _load_object_mapping

            staged_sub_rule_results = []
            for sub_rule in sub_rules:
                rule_fields = {
                    str(item.get("index", ""))
                    for item in sub_rule.get("normalize", []) or []
                    if isinstance(item, dict)
                }
                staged_sub_rule_results.append(
                    {
                        "rule_name": str(sub_rule.get("name", "")),
                        "mappings": [
                            row
                            for row in mapping_rows
                            if str(row.get("原始字段名", "")) in rule_fields
                        ],
                    }
                )
            object_mapping_path = Path(__file__).resolve().parent.parent / "config" / "对象.xlsx"
            object_entity_map = _load_object_mapping(str(object_mapping_path))
            staged_mapped_sub_rules = apply_field_mapping_to_sub_rules(
                sub_rules,
                staged_sub_rule_results,
                object_entity_map,
            )

        # 把字段映射回填到上传的解码配置，产出 Base64 下载，供用户取回填充后的配置（与枚举填充一致）。
        filled_config_payload = None
        decoded_data = _session_get(context.session, "decoded_data")
        if isinstance(decoded_data, dict) and decoded_data:
            from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_config
            from agent.tools.standard_mapper import _load_object_mapping

            object_mapping_path = Path(__file__).resolve().parent.parent / "config" / "对象.xlsx"
            object_entity_map = _load_object_mapping(str(object_mapping_path))
            filled_config = apply_field_mapping_to_config(
                decoded_data, mapping_rows, object_entity_map
            )
            _session_set(context.session, "decoded_data", filled_config)
            filled_config_payload = _build_config_artifact(
                filled_config, len(typed_mappings)
            ).content

        # 所有类型校验和领域计算完成后才提交，失败路径不会留下中间状态。
        await _publish_progress(
            context,
            step,
            ProgressPhase.WRITEBACK,
            ProgressStatus.RUNNING,
            "field_mapping_writing",
        )
        _session_set(context.session, "last_mapping_data", mapping_rows)
        if staged_sub_rule_results is not None and staged_mapped_sub_rules is not None:
            _session_set(context.session, "sub_rule_mapping_results", staged_sub_rule_results)
            _session_set(context.session, "mapped_sub_rules", staged_mapped_sub_rules)
        return _success(
            step,
            FieldMappingArtifact(
                mappings=typed_mappings,
                item_count=len(typed_mappings),
                filled_config=filled_config_payload,
            ),
        )
    async def _execute_threat_mapping(
        self,
        step: ThreatMappingStep,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """只使用显式值或本次依赖的枚举产物调用威胁映射 Agent。"""
        from web.parsers import parse_json_threat_result

        if step.source_ref == "user.values":
            values = list(step.values)
        else:
            dependency_id = step.source_ref.removeprefix("step:")
            dependency = dependencies.get(dependency_id)
            artifact = dependency.artifact if dependency else None
            if not isinstance(artifact, EnumValuesArtifact):
                return _failed(step, "dependency_type_mismatch", "依赖产物不是枚举值")
            values = list(artifact.values)
        model_input = json.dumps({"values": values}, ensure_ascii=False)
        content = await self._run_member("ThreatAgent", model_input)
        mapping_rows = parse_json_threat_result(content)
        if not mapping_rows:
            return _failed(step, "threat_mapping_empty", "威胁映射未生成有效结果")
        _session_set(context.session, "last_threat_data", mapping_rows)
        typed_mappings = tuple(ThreatMappingRow.model_validate(row) for row in mapping_rows)
        return _success(
            step,
            ThreatMappingArtifact(mappings=typed_mappings, item_count=len(typed_mappings)),
        )

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
        members = getattr(self._team, "members", ())
        member = next(
            (candidate for candidate in members if getattr(candidate, "name", "") == member_name),
            None,
        )
        if member is None:
            raise RuntimeError(f"未配置专业 Agent: {member_name}")

        async_runner = getattr(member, "arun", None)
        if callable(async_runner):
            response_stream = async_runner(model_input, stream=True, stream_events=True)
            if inspect.isawaitable(response_stream):
                response_stream = await response_stream
            if hasattr(response_stream, "__aiter__"):
                completed_content = None
                completed_metrics = None
                async for event in response_stream:
                    event_name = str(getattr(event, "event", ""))
                    if event_name.endswith("RunError"):
                        raise RuntimeError("专业 Agent 返回运行错误事件")
                    if event_name.endswith("RunCompleted"):
                        completed_content = getattr(event, "content", None)
                        completed_metrics = getattr(event, "metrics", None)
                if completed_content is None:
                    raise RuntimeError("专业 Agent 未返回完成内容")
                if completed_metrics is not None:
                    logger.info(
                        "[MODEL_USAGE] 专业模型 token 统计: plan_id=%s step_id=%s "
                        "batch=%s member=%s input_tokens=%s output_tokens=%s total_tokens=%s",
                        plan_id,
                        step_id,
                        batch_number if batch_number is not None else "none",
                        member_name,
                        getattr(completed_metrics, "input_tokens", 0),
                        getattr(completed_metrics, "output_tokens", 0),
                        getattr(completed_metrics, "total_tokens", 0),
                    )
                return completed_content
            return getattr(response_stream, "content", response_stream)

        # 仅为尚未迁移的测试替身保留同步兼容；生产 Agent 必须提供 arun。
        sync_runner = getattr(member, "run", None)
        if not callable(sync_runner):
            raise RuntimeError(f"专业 Agent 不支持异步执行: {member_name}")
        response = await asyncio.to_thread(sync_runner, model_input)
        return getattr(response, "content", response)

def _success(step: StepSpec, artifact: StepArtifact) -> StepResult:
    """把已验证的类型化领域产物转换为统一成功结果。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.SUCCESS,
        artifact=artifact,
        message="步骤执行成功",
    )
def _failed(step: StepSpec, error_code: str, message: str) -> StepResult:
    """把领域失败转换为稳定错误码，不携带敏感原值。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.FAILED,
        error_code=error_code,
        message=message,
    )


def _needs_input(step: StepSpec, error_code: str, message: str) -> StepResult:
    """把缺失输入转换为待输入结果，阻止执行器继续后续步骤。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.NEEDS_INPUT,
        error_code=error_code,
        message=message,
    )


def create_default_adapters(team: Any) -> dict[str, StepAdapter]:
    """创建统一执行器的默认适配器表，操作类型是唯一分派键。"""
    professional_adapter = ProfessionalAgentAdapter(team)
    return {
        "log_parse": professional_adapter,
        "field_mapping": professional_adapter,
        "enum_extract": professional_adapter,
        "threat_mapping": professional_adapter,
        "fill": FillAdapter(),
        "remove_mapping": RemoveMappingAdapter(),
        "export": ExportAdapter(),
    }
