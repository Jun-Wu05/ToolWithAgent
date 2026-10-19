"""字段映射适配器：编排批处理结果、领域产物与原子会话写回。"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping
from typing import Any

from agent.shared.logger import get_logger
from application.adapters.shared import (
    REPO_ROOT, _build_config_artifact, _count_tagged_normalize, _failed,
    _publish_progress, _retry_delay_seconds, _needs_input,
    _success, run_member_stream,
)
from application.execution import ExecutionContext
from application.field_mapping_batch import (
    FieldMappingBatchError, FieldMappingBatchRunner, FieldMappingExecutionPolicy,
)
from application.recovery import is_transient
from contracts.progress import ProgressPhase, ProgressStatus
from contracts.planner_models import (
    FieldMappingArtifact, FieldMappingRow, FieldMappingStep, StepResult, StepStatus,
)

logger = get_logger("execution_adapters")


class FieldMappingAdapter:
    """连接 StepSpec、批处理 Runner、领域产物与 Session 原子提交。"""

    def __init__(
        self,
        team: Any,
        mapping_policy: FieldMappingExecutionPolicy | None = None,
        candidate_retriever: Any | None = None,
        event_classifier: Any | None = None,
        batch_runner: Any | None = None,
    ) -> None:
        """保存批处理 Runner、执行策略及领域服务接缝。

        candidate_retriever 为结构化候选检索器（返回 #180 候选表），
        供冲突裁决直接消费；批处理 prompt 需要的 markdown 文本在
        _build_prompt_prequery 注入边界处渲染。对象归属由标准字段目录
        确定性解析（#177），不再有对象表装载接缝。
        """
        self._mapping_policy = mapping_policy or FieldMappingExecutionPolicy()
        self._candidate_retriever = candidate_retriever
        self._event_classifier = event_classifier
        self._team = team
        self._batch_runner = (
            batch_runner
            if batch_runner is not None
            else FieldMappingBatchRunner(
                team,
                policy=self._mapping_policy,
                candidate_retriever=self._build_prompt_prequery(),
            )
        )

    def _build_prompt_prequery(self) -> Any | None:
        """把结构化候选检索器适配成 prompt 注入需要的增强候选文本检索器。

        未注入时回落结构化默认检索（batch_retrieve_candidates_table）；
        渲染使用 #189 的 ``render_candidates_enriched``（附对象/属性类型/
        描述/枚举白名单）。注入假件时每批只调用一次检索器。
        """
        retriever = self._candidate_retriever
        if retriever is None:
            from agent.core.field_retriever import batch_retrieve_candidates_table

            retriever = batch_retrieve_candidates_table

        def prequery(fields: list[str]) -> str:
            """取结构化候选表并渲染为 prompt 注入用的增强候选文本。"""
            table = retriever(fields)
            if not table:
                return ""
            from agent.core.field_retriever import render_candidates_enriched

            return render_candidates_enriched(table, top_k=5)

        return prequery

    async def execute(
        self,
        step: FieldMappingStep,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult] | None = None,
    ) -> StepResult:
        """校验步骤类型并执行字段映射。"""
        if not isinstance(step, FieldMappingStep):
            raise TypeError("FieldMappingAdapter 只接受 FieldMappingStep")
        return await self._execute_field_mapping(step, context)

    async def _execute_field_mapping(
        self, step: FieldMappingStep, context: ExecutionContext
    ) -> StepResult:
        """运行批处理，验证完整结果，再计算产物并一次性提交 Session。"""
        classification = context.session.log_classification
        rule_source_fields = None
        mappable_fields = list(context.session_facts.mappable_fields)
        if (
            not mappable_fields
            and context.session_facts.has_decoded_config
            and context.session_facts.decoded_mapped_field_count > 0
            and context.session_facts.decoded_unmapped_field_count == 0
        ):
            skipped_count = context.session_facts.decoded_mapped_field_count
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus.SUCCESS,
                message=(
                    "所有字段均已映射，无需再次执行；"
                    f"跳过已映射 {skipped_count} 个（保留原映射）"
                ),
            )
        if isinstance(classification, dict) and classification:
            from contracts.rule_source import RuleSourceFields

            rule_source_fields = RuleSourceFields.from_value(
                context.session.rule_source_fields
            )
            if rule_source_fields is None:
                context.session.pending_rule_source_step = step
                return _needs_input(
                    step,
                    "data_source_fields_required",
                    "请填写数据源产品和数据源厂商后继续；数据源可留空自动生成",
                )
        simplified_data = context.session.simplified_data or {}
        original_log_sample = (
            simplified_data.get("original_log_sample", "")
            if isinstance(simplified_data, Mapping) else ""
        )
        decoded_data = context.session.decoded_data

        # 子规则获取前置（#189）：语义与原先后置获取一致（session 优先，缺失时生成）。
        had_existing_mapped_rules = bool(context.session.mapped_sub_rules)
        sub_rules = copy.deepcopy(context.session.mapped_sub_rules or [])
        raw_log_lines = context.session.raw_log_lines or []
        if not sub_rules:
            if isinstance(classification, dict) and classification:
                from agent.tools.rule_generator import generate_sub_rules

                sub_rules = generate_sub_rules(
                    classification,
                    all_logs_str="\n".join(str(line) for line in raw_log_lines),
                    rule_source_fields=rule_source_fields,
                )

        # #189 确定性字段名命中：精确/同义词命中 8 个枚举目标的字段绕过 LLM
        # 字段判断，直接作为已匹配行；其余字段进入批处理主路径（行为不变）。
        resolved_enum_fields: dict[str, tuple[str, str]] = {}
        llm_fields: list[str] = []
        from agent.core.standard_field_catalog import resolve_enum_field

        for field_name in mappable_fields:
            hit = resolve_enum_field(field_name)
            if hit is not None:
                resolved_enum_fields[field_name] = hit
            else:
                llm_fields.append(field_name)

        # 值画像（代码全量扫描）：第一阶段输入注入，第二阶段复用同一份
        value_profiles_by_field: dict[str, list] = {}
        enum_profiles_sub: dict = {}
        enum_profiles_config: dict = {}
        if llm_fields or resolved_enum_fields:
            from application.standard_enum_mapping import (
                build_value_profiles_from_config,
                build_value_profiles_from_logs,
            )

            if sub_rules:
                enum_profiles_sub = build_value_profiles_from_logs(
                    sub_rules,
                    [str(line) for line in raw_log_lines],
                    classification if isinstance(classification, dict) else None,
                )
            if isinstance(decoded_data, (dict, list)) and decoded_data:
                enum_profiles_config = build_value_profiles_from_config(decoded_data)
            for profile in (*enum_profiles_sub.values(), *enum_profiles_config.values()):
                value_profiles_by_field.setdefault(profile.field, []).append(profile)

        async def publish_batch_progress(
            phase: ProgressPhase, status: ProgressStatus, message_code: str, **details: Any
        ) -> None:
            """把 Runner 的批次进度绑定到当前计划与步骤。"""
            await _publish_progress(context, step, phase, status, message_code, **details)

        try:
            runner_rows = await self._batch_runner.run(
                llm_fields,
                original_log_sample=original_log_sample,
                plan_id=context.plan_id,
                step_id=step.step_id,
                publish_progress=publish_batch_progress,
                value_profiles=value_profiles_by_field or None,
            )
        except FieldMappingBatchError as error:
            logger.error(
                "[BATCH_FAILED] 字段映射原子失败: plan_id=%s step_id=%s "
                "batch=%s error_category=%s",
                context.plan_id, step.step_id, error.batch_number, error.error_code,
            )
            return _failed(step, error.error_code, str(error))
        mapping_rows = runner_rows + [
            {
                "原始字段名": field_name,
                "系统属性名称": target,
                "匹配状态": "匹配成功",
            }
            for field_name, (target, _source) in resolved_enum_fields.items()
        ]
        # 恢复输入字段顺序，保持展示与既有行为一致
        rows_by_field = {str(row.get("原始字段名", "")): row for row in mapping_rows}
        mapping_rows = [rows_by_field[field] for field in mappable_fields if field in rows_by_field]

        await _publish_progress(
            context, step, ProgressPhase.VALIDATION, ProgressStatus.RUNNING,
            "field_mapping_validating",
        )
        if len(mapping_rows) != len(mappable_fields):
            return _failed(step, "field_mapping_incomplete", "字段映射结果数量与输入字段数量不一致")

        from application.field_mapping_conflicts import (
            format_field_mapping_conflicts,
            log_field_mapping_conflicts,
            resolve_field_mapping_conflicts,
        )

        conflict_outcome = resolve_field_mapping_conflicts(
            mapping_rows,
            decoded_data=decoded_data,
            candidate_retriever=self._candidate_retriever,
        )
        mapping_rows = list(conflict_outcome.rows)
        conflict_summary = format_field_mapping_conflicts(conflict_outcome.details)
        log_field_mapping_conflicts(
            conflict_outcome.details, plan_id=context.plan_id, step_id=step.step_id
        )

        # #189 第二阶段：仅对本轮新命中 8 类枚举字段的画像调用一次受约束归类，
        # 之后全部硬校验；失败画像局部关闭（零写入 + 对应子规则内降级未匹配）。
        from application.standard_enum_mapping import (
            run_enum_review_stage,
            summarize_enum_outcomes,
        )

        async def call_enum_model(prompt: str) -> str:
            """第二阶段归类调用：复用 FieldMappingAgent 与既有看门狗超时。"""
            return await asyncio.wait_for(
                run_member_stream(
                    self._team, "FieldMappingAgent", prompt,
                    plan_id=context.plan_id, step_id=step.step_id,
                ),
                timeout=self._mapping_policy.watchdog_timeout_seconds,
            )

        enum_outcomes_sub, enum_outcomes_config = await run_enum_review_stage(
            mapping_rows,
            profiles_sub=enum_profiles_sub,
            profiles_config=enum_profiles_config,
            resolved_enum_fields=resolved_enum_fields,
            call_model=call_enum_model,
        )
        enum_summary = summarize_enum_outcomes({
            **{("sub", *key): outcome for key, outcome in enum_outcomes_sub.items()},
            **{("cfg", *key): outcome for key, outcome in enum_outcomes_config.items()},
        })

        typed_mappings = tuple(FieldMappingRow.model_validate(row) for row in mapping_rows)
        staged_sub_rule_results = staged_mapped_sub_rules = None
        event_annotation_summary: str | None = None
        event_annotation_rows: tuple = ()
        if sub_rules:
            from agent.tools.rule_generator.field_mapping import (
                apply_field_mapping_to_sub_rules,
            )

            staged_sub_rule_results = []
            for sub_rule in sub_rules:
                rule_fields = {
                    str(item.get("index", ""))
                    for item in sub_rule.get("normalize", []) or []
                    if isinstance(item, dict)
                }
                staged_sub_rule_results.append({
                    "rule_name": str(sub_rule.get("name", "")),
                    "mappings": [
                        dict(row) for row in mapping_rows
                        if str(row.get("原始字段名", "")) in rule_fields
                    ],
                })
            # #177：标准字段目录是对象归属 SSOT（名称/对象由目录确定性解析），
            # 不再加载 对象.xlsx（加载失败静默空表 + 未知名称默认「事件」的
            # 两个缺陷由此一并消除）。
            staged_mapped_sub_rules = apply_field_mapping_to_sub_rules(
                sub_rules, staged_sub_rule_results
            )
            if enum_outcomes_sub:
                from agent.shared.mapping_utils import apply_enum_outcomes

                apply_enum_outcomes(staged_mapped_sub_rules, enum_outcomes_sub)
            annotation_outcome = await self._annotate_event_names(
                step, context, staged_mapped_sub_rules
            )
            if isinstance(annotation_outcome, StepResult):
                return annotation_outcome
            staged_mapped_sub_rules, event_annotation_summary, event_annotation_rows = (
                annotation_outcome
            )

        staged_decoded_data = None
        download_kind = None
        download_content = None
        has_decoded_config = "session.decoded_config" in context.session_facts.available_config_refs
        if has_decoded_config and isinstance(decoded_data, (dict, list)) and decoded_data:
            from agent.tools.rule_generator.field_mapping import (
                apply_field_mapping_to_config,
                find_non_catalog_field_entities,
            )

            # 上传配置既有非法组合只诊断不改写（原样保留语义，#177）
            illegal = find_non_catalog_field_entities(decoded_data)
            if illegal:
                logger.warning(
                    "[FIELD_MAPPING] 上传配置存在非目录字段/对象组合（原样保留，仅诊断）: "
                    "count=%s samples=%s",
                    len(illegal),
                    [f"{index}:{field}/{entity}" for index, field, entity in illegal[:5]],
                )
            staged_decoded_data = apply_field_mapping_to_config(
                copy.deepcopy(decoded_data), mapping_rows
            )
            if enum_outcomes_config:
                from agent.shared.mapping_utils import apply_enum_outcomes

                apply_enum_outcomes(staged_decoded_data, enum_outcomes_config)
            download_kind = "mapped_config"
            download_content = _build_config_artifact(
                staged_decoded_data, len(typed_mappings)
            ).content
            logger.info(
                "[FIELD_MAPPING_FILLED_CONFIG] 回填配置产物已生成: "
                "plan_id=%s step_id=%s root_type=%s content_bytes=%s",
                context.plan_id, step.step_id, type(staged_decoded_data).__name__,
                len(download_content.encode("utf-8")),
            )
        elif staged_mapped_sub_rules is not None:
            download_kind = "mapped_sub_rules"
            download_content = _build_config_artifact(
                staged_mapped_sub_rules, len(typed_mappings)
            ).content
            logger.info(
                "[FIELD_MAPPING_MAPPED_SUB_RULES] 映射后子规则产物已生成: "
                "plan_id=%s step_id=%s rule_count=%s content_bytes=%s",
                context.plan_id, step.step_id, len(staged_mapped_sub_rules),
                len(download_content.encode("utf-8")),
            )

        await _publish_progress(
            context, step, ProgressPhase.WRITEBACK, ProgressStatus.RUNNING,
            "field_mapping_writing",
        )
        context.session.last_mapping_data = mapping_rows
        if staged_sub_rule_results is not None and staged_mapped_sub_rules is not None:
            context.session.sub_rule_mapping_results = staged_sub_rule_results
            context.session.mapped_sub_rules = staged_mapped_sub_rules
        if staged_decoded_data is not None:
            context.session.decoded_data = staged_decoded_data

        updated_normalize_count = 0
        decoded_added_count = 0
        if staged_mapped_sub_rules is not None:
            updated_normalize_count += max(
                0, _count_tagged_normalize(staged_mapped_sub_rules)
                - _count_tagged_normalize(sub_rules)
            )
        if staged_decoded_data is not None:
            decoded_added_count = max(
                0, _count_tagged_normalize(staged_decoded_data)
                - _count_tagged_normalize(decoded_data)
            )
            updated_normalize_count += decoded_added_count
        logger.info(
            "[FIELD_MAPPING_WRITEBACK] plan_id=%s step_id=%s 唯一字段映射数=%s "
            "实际更新normalize项数=%s",
            context.plan_id, step.step_id, len(typed_mappings), updated_normalize_count,
        )
        message = (
            f"字段映射完成：唯一字段 {len(typed_mappings)} 项，"
            f"实际更新 {updated_normalize_count} 个 normalize 项"
        )
        if staged_decoded_data is not None:
            message = (
                f"{message}；上传规则新增映射 {decoded_added_count} 个 / "
                f"跳过已映射 {context.session_facts.decoded_mapped_field_count} 个"
                "（保留原映射）"
            )
        if enum_summary:
            message = f"{message}；{enum_summary}"
        if conflict_summary:
            message = f"{message}；{conflict_summary}"
        if event_annotation_summary:
            message = f"{message}；{event_annotation_summary}"
        if had_existing_mapped_rules and staged_mapped_sub_rules is not None:
            message = (
                f"{message}；⚠️ 重新映射已重新生成子规则，"
                "此前手动调整（字段增删/事件名称修改）已被覆盖"
            )
        return _success(
            step,
            FieldMappingArtifact(
                mappings=typed_mappings, item_count=len(typed_mappings),
                event_annotations=event_annotation_rows, download_kind=download_kind,
                download_content=download_content,
            ),
            message=message,
        )

    async def _annotate_event_names(
        self,
        step: FieldMappingStep,
        context: ExecutionContext,
        mapped_sub_rules: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str | None, tuple] | StepResult:
        """判定并写入每条子规则的事件名称和绑定事件级别。"""
        from agent.shared import event_classify

        judgments: dict[str, str] = {}
        uncertain: list[str] = []
        for attempt in range(2):
            try:
                judgments, uncertain = await event_classify.classify_sub_rule_events(
                    mapped_sub_rules, llm_client=self._event_classifier
                )
                break
            except Exception as error:  # noqa: BLE001 - 适配层统一判定可重试错误
                if attempt == 0 and is_transient(error):
                    await asyncio.sleep(
                        _retry_delay_seconds(error, self._mapping_policy.retry_delay_seconds)
                    )
                    continue
                logger.warning(
                    "[EVENT_NAME_ANNOTATE] 判定失败: plan_id=%s step_id=%s error=%s",
                    context.plan_id, step.step_id, error,
                )
                return _failed(step, "event_classify_failed", "事件名称判定失败，请重试")

        annotated = event_classify.apply_event_fields_to_sub_rules(mapped_sub_rules, judgments)
        if not judgments and not uncertain:
            return mapped_sub_rules, "", ()
        threat_count = sum(
            1 for value in judgments.values() if value in event_classify.THREAT_EVENT_NAMES
        )
        summary = (
            f"事件名称已标注 {len(judgments)} 条（威胁 {threat_count}、"
            f"非威胁 {len(judgments) - threat_count}）"
        )
        if uncertain:
            summary += f"；待人工确认 {len(uncertain)} 条（{'、'.join(uncertain)}）"
        logger.info(
            "[EVENT_NAME_ANNOTATE] plan_id=%s step_id=%s judged=%s uncertain=%s",
            context.plan_id, step.step_id, len(judgments), len(uncertain),
        )
        from contracts.planner_models import EventAnnotationRow

        annotation_rows: list[EventAnnotationRow] = []
        uncertain_set = set(uncertain)
        for rule in mapped_sub_rules:
            rule_name = str(rule.get("name", ""))
            event_name = judgments.get(rule_name, "")
            if event_name:
                annotation_rows.append(EventAnnotationRow(
                    rule_name=rule_name, event_name=event_name,
                    event_level=event_classify.EVENT_NAME_LEVEL_BINDING[event_name],
                    status="judged",
                ))
            elif rule_name in uncertain_set:
                annotation_rows.append(EventAnnotationRow(rule_name=rule_name, status="uncertain"))
        return annotated, summary or None, tuple(annotation_rows)


__all__ = ["FieldMappingAdapter", "FieldMappingBatchError", "FieldMappingExecutionPolicy"]
