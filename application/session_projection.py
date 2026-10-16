"""把运行时会话状态投影为供 Planner 使用的安全事实快照。"""

from collections.abc import Mapping
from typing import Any

from agent.shared.event_classify import (
    EVENT_NAME_LEVEL_BINDING,
    THREAT_EVENT_NAMES,
    THREAT_TYPE_FIELD,
    read_entity_event_name,
)
from agent.shared.mapping_utils import collect_config_names, iter_normalize_entries
from application.adapters.shared import _read_config
from application.artifact_targets import resolve_standard_target
from contracts.planner_models import ConfigRef, ExecutionReport
from contracts.session_artifacts import (
    ArtifactTargetBinding,
    EnumArtifactSlot,
    ReferenceableArtifactFact,
    ThreatArtifactSlot,
)
from contracts.session_facts import (
    EventAnnotationFact,
    ExecutionSummary,
    SessionFacts,
    StepSummary,
)


def summarize_report(report: ExecutionReport) -> ExecutionSummary:
    """把执行账本收缩为不含业务值的 Planner 安全摘要。"""
    return ExecutionSummary(
        plan_id=report.plan_id,
        steps=tuple(
            StepSummary(
                step_id=result.step_id,
                type=result.operation_type,
                status=result.status,
                error_code=result.error_code,
                artifact_kinds=(result.artifact.artifact_type,) if result.artifact else (),
                artifact_count=result.artifact.item_count if result.artifact else 0,
            )
            for result in report.results
        ),
    )


def _recent_execution(session: Any) -> tuple[ExecutionSummary, ...]:
    """按最新优先投影两个类型化摘要槽位，损坏的兼容值按不存在处理。"""
    summaries: list[ExecutionSummary] = []
    for key in ("current_execution", "previous_execution"):
        value = _read_session_value(session, key)
        if value is None:
            continue
        try:
            summaries.append(
                value
                if isinstance(value, ExecutionSummary)
                else ExecutionSummary.model_validate(value)
            )
        except (TypeError, ValueError):
            continue
    return tuple(summaries)


def _read_session_value(session: Any, key: str, default: Any = None) -> Any:
    """兼容 SessionState 与测试字典。"""
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _collect_decoded_field_mapping_state(
    decoded_data: Any,
) -> tuple[set[str], int, int]:
    """按非空 field 识别上传配置的已映射字段；mappings 不参与判定。"""
    from agent.tools.rule_generator.field_mapping import EXCLUDED_FIELD_INDICES

    mapped_indices: set[str] = set()
    mapped_count = 0
    unmapped_count = 0
    for _path, _position, _owner, entry in iter_normalize_entries(
        decoded_data, excluded_indexes=EXCLUDED_FIELD_INDICES
    ):
        index = str(entry.get("index") or "").strip()
        if str(entry.get("field") or "").strip():
            mapped_indices.add(index)
            mapped_count += 1
        else:
            unmapped_count += 1
    return mapped_indices, mapped_count, unmapped_count


def _collect_field_pools(
    session: Any, decoded_mapped_indices: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """构建 Planner 点名词典与字段映射候选池。"""
    from agent.tools.rule_generator.field_mapping import EXCLUDED_FIELD_INDICES
    from application.field_source import extract_log_fields_for_mapping

    available_fields: list[str] = []
    seen_available_fields: set[str] = set()
    mappable_fields: list[str] = []
    seen_mappable_fields: set[str] = set()
    mapped_standard_fields: set[str] = set()

    def append_fields(values: Any, target: list[str], seen: set[str]) -> None:
        for item in values or []:
            field_name = str(item).strip()
            if field_name and field_name not in seen and field_name not in EXCLUDED_FIELD_INDICES:
                seen.add(field_name)
                target.append(field_name)

    classification = _read_session_value(session, "log_classification")
    raw_log_lines = _read_session_value(session, "raw_log_lines", []) or []
    log_fields = extract_log_fields_for_mapping(classification, raw_log_lines)
    mapped_sub_rules = _read_session_value(session, "mapped_sub_rules", []) or []
    base_fields = log_fields or _read_session_value(session, "decoded_fields", []) or []
    append_fields(base_fields, available_fields, seen_available_fields)
    # 日志/子规则来源仍全量映射；纯上传回退只发送 field 为空的原始字段。
    mappable_base_fields = (
        base_fields
        if log_fields or mapped_sub_rules
        else [field for field in base_fields if str(field).strip() not in decoded_mapped_indices]
    )
    append_fields(mappable_base_fields, mappable_fields, seen_mappable_fields)
    for sub_rule in mapped_sub_rules:
        if not isinstance(sub_rule, Mapping):
            continue
        for normalization in sub_rule.get("normalize", []) or []:
            if isinstance(normalization, Mapping):
                original_field = normalization.get("index")
                standard_field = normalization.get("field")
                append_fields(
                    (original_field, standard_field),
                    available_fields,
                    seen_available_fields,
                )
                append_fields(
                    (original_field,),
                    mappable_fields,
                    seen_mappable_fields,
                )
                standard_name = str(standard_field or "").strip()
                if standard_name:
                    mapped_standard_fields.add(standard_name)
    return (
        tuple(available_fields),
        tuple(field for field in mappable_fields if field not in mapped_standard_fields),
    )


def _collect_enum_target_fields(enum_preview: Any) -> tuple[str, ...]:
    targets = {
        str(row["目标字段"]).strip()
        for row in enum_preview or []
        if isinstance(row, Mapping) and row.get("目标字段") is not None and str(row["目标字段"]).strip()
    }
    return tuple(sorted(targets))


def _count_enum_values(enum_result: Any) -> int:
    if not isinstance(enum_result, Mapping):
        return 0
    for key in ("value", "values", "enum_values", "data"):
        values = enum_result.get(key)
        if isinstance(values, (list, tuple, set)):
            return len(values)
    return 0


def _count_normalize_entries(value: Any) -> int:
    """统计配置树中 normalize 条目数（dict 条目口径，schema 下与列表长度一致）。"""
    return sum(1 for _ in iter_normalize_entries(value, require_index=False))


def _target_bindings(
    session: Any, source_field: str | None, config_refs: tuple[ConfigRef, ...]
) -> tuple[ArtifactTargetBinding, ...]:
    """枚举产物的填充目标仍按 source_field 血缘解析（多目标合法）。"""
    if not source_field:
        return ()
    bindings: list[ArtifactTargetBinding] = []
    for config_ref in config_refs:
        target = resolve_standard_target(_read_config(session, config_ref), source_field)
        if target:
            bindings.append(ArtifactTargetBinding(config_ref=config_ref, target_field=target))
    return tuple(bindings)


def _has_threat_type_entry(config: Any) -> bool:
    """判断配置中是否存在威胁类型条目（index 或 field 命中，含未映射条目）。

    消费 agent.shared.mapping_utils.iter_normalize_entries——与
    apply_fill_to_config 的「同构」自 #313 起是字面事实而非注释约定。
    """
    return any(
        entry.get("index") == THREAT_TYPE_FIELD
        or entry.get("field") == THREAT_TYPE_FIELD
        for _path, _position, _owner, entry in iter_normalize_entries(
            config, require_index=False
        )
    )


def _threat_target_bindings(
    session: Any, config_refs: tuple[ConfigRef, ...]
) -> tuple[ArtifactTargetBinding, ...]:
    """威胁产物填充目标固定为「威胁类型」（#173 修复 1），不再按血缘推导。

    仅当配置已含威胁类型条目（通常由威胁链路自动添加）时发布绑定，
    保持「绑定 = 当前可操作」的目录语义。
    """
    return tuple(
        ArtifactTargetBinding(config_ref=config_ref, target_field=THREAT_TYPE_FIELD)
        for config_ref in config_refs
        if _has_threat_type_entry(_read_config(session, config_ref))
    )


def _referenceable_artifacts(
    session: Any, config_refs: tuple[ConfigRef, ...]
) -> tuple[ReferenceableArtifactFact, ...]:
    facts: list[ReferenceableArtifactFact] = []
    raw_enum = _read_session_value(session, "latest_enum_artifact")
    try:
        enum_slot = raw_enum if isinstance(raw_enum, EnumArtifactSlot) else EnumArtifactSlot.model_validate(raw_enum) if raw_enum is not None else None
    except (TypeError, ValueError):
        enum_slot = None
    if enum_slot is not None:
        facts.append(ReferenceableArtifactFact(
            source_ref="session.artifacts.enum_values",
            artifact_type="enum_values",
            source_field=enum_slot.source_field,
            item_count=enum_slot.artifact.item_count,
            target_bindings=_target_bindings(session, enum_slot.source_field, config_refs),
        ))

    raw_threat = _read_session_value(session, "latest_threat_artifact")
    try:
        threat_slot = raw_threat if isinstance(raw_threat, ThreatArtifactSlot) else ThreatArtifactSlot.model_validate(raw_threat) if raw_threat is not None else None
    except (TypeError, ValueError):
        threat_slot = None
    if threat_slot is not None:
        facts.append(ReferenceableArtifactFact(
            source_ref="session.artifacts.threat_mapping",
            artifact_type="threat_mapping",
            source_field=threat_slot.source_field,
            item_count=threat_slot.artifact.item_count,
            target_bindings=_threat_target_bindings(session, config_refs),
        ))
    return tuple(facts)


def _collect_rule_names(config: Any) -> tuple[str, ...]:
    """递归收集规则名（已收口 mapping_utils.collect_config_names，#313）。"""
    return tuple(collect_config_names(config))


def _collect_event_annotations(config: Any) -> tuple[EventAnnotationFact, ...]:
    facts: list[EventAnnotationFact] = []
    for entity in config or []:
        if not isinstance(entity, Mapping):
            continue
        name = entity.get("name")
        if not isinstance(name, str) or not name:
            continue
        event_name = read_entity_event_name(entity) or ""
        facts.append(EventAnnotationFact(
            rule_name=name,
            event_name=event_name,
            event_level=EVENT_NAME_LEVEL_BINDING.get(event_name, ""),
        ))
    return tuple(facts)


def _collect_threat_source_fields(
    mapped_sub_rules: Any, annotations: tuple[EventAnnotationFact, ...]
) -> tuple[str, ...]:
    """返回覆盖所有威胁子规则的原始字段，保持首条规则中的字段顺序。"""
    from application.threat_chain_policy import collect_threat_field_pools

    threat_names = tuple(
        item.rule_name for item in annotations if item.event_name in THREAT_EVENT_NAMES
    )
    pools = collect_threat_field_pools(mapped_sub_rules, threat_names)
    if not threat_names or len(pools) != len(threat_names):
        return ()
    first = pools[threat_names[0]]
    shared = set(first).intersection(*(set(pools[name]) for name in threat_names[1:]))
    return tuple(field for field in first if field in shared and field != THREAT_TYPE_FIELD)


def build_session_facts(session: Any) -> SessionFacts:
    """把会话状态投影为不可变安全快照；缺失状态按不可用处理。"""
    enum_preview = _read_session_value(session, "enum_preview", []) or []
    mapped_sub_rules = _read_session_value(session, "mapped_sub_rules", []) or []
    decoded_data = _read_session_value(session, "decoded_data")
    decoded_mapped_indices, decoded_mapped_count, decoded_unmapped_count = (
        _collect_decoded_field_mapping_state(decoded_data)
    )
    available_fields, mappable_fields = _collect_field_pools(
        session, decoded_mapped_indices
    )
    event_annotations = _collect_event_annotations(mapped_sub_rules)
    config_refs: tuple[ConfigRef, ...] = tuple(
        ref
        for ref, config in (
            ("session.decoded_config", decoded_data),
            ("session.mapped_sub_rules", mapped_sub_rules),
        )
        if _count_normalize_entries(config)
    )
    return SessionFacts(
        has_decoded_config=bool(decoded_data),
        has_logs=bool((_read_session_value(session, "original_log", []) or []) or (_read_session_value(session, "raw_log_lines", []) or [])),
        has_log_classification=bool(_read_session_value(session, "log_classification")),
        has_mapped_sub_rules=bool(mapped_sub_rules),
        available_config_refs=config_refs,
        available_fields=available_fields,
        mappable_fields=mappable_fields,
        threat_source_fields=_collect_threat_source_fields(
            mapped_sub_rules, event_annotations
        ),
        recent_execution=_recent_execution(session),
        decoded_mapped_field_count=decoded_mapped_count,
        decoded_unmapped_field_count=decoded_unmapped_count,
        enum_mapping_target_fields=_collect_enum_target_fields(enum_preview),
        enum_mapping_row_count=len(enum_preview),
        existing_enum_value_count=_count_enum_values(_read_session_value(session, "last_enum_extract_result")),
        existing_threat_mapping_count=len(_read_session_value(session, "last_threat_data", []) or []),
        mapped_sub_rule_count=len(mapped_sub_rules),
        mapped_sub_rule_names=_collect_rule_names(mapped_sub_rules),
        decoded_config_rule_names=_collect_rule_names(decoded_data),
        event_annotations=event_annotations,
        referenceable_artifacts=_referenceable_artifacts(session, config_refs),
    )
