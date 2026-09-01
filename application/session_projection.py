"""把运行时会话状态投影为供 Planner 使用的安全事实快照。"""

from collections.abc import Mapping
from typing import Any

from agent.shared.event_classify import EVENT_NAME_LEVEL_BINDING, read_entity_event_name
from application.artifact_targets import resolve_standard_target
from contracts.planner_models import ConfigRef
from contracts.session_artifacts import (
    ArtifactTargetBinding,
    EnumArtifactSlot,
    ReferenceableArtifactFact,
    ThreatArtifactSlot,
)
from contracts.session_facts import EventAnnotationFact, SessionFacts


def _read_session_value(session: Any, key: str, default: Any = None) -> Any:
    """兼容 SessionState 与测试字典。"""
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _collect_field_pools(session: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
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
    base_fields = log_fields or _read_session_value(session, "decoded_fields", []) or []
    append_fields(base_fields, available_fields, seen_available_fields)
    append_fields(base_fields, mappable_fields, seen_mappable_fields)
    for sub_rule in _read_session_value(session, "mapped_sub_rules", []) or []:
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
    if isinstance(value, Mapping):
        own = len(value["normalize"]) if isinstance(value.get("normalize"), list) else 0
        return own + sum(_count_normalize_entries(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_normalize_entries(item) for item in value)
    return 0


def _read_config(session: Any, config_ref: ConfigRef) -> Any:
    key = "decoded_data" if config_ref == "session.decoded_config" else "mapped_sub_rules"
    return _read_session_value(session, key)


def _target_bindings(
    session: Any, source_field: str | None, config_refs: tuple[ConfigRef, ...]
) -> tuple[ArtifactTargetBinding, ...]:
    if not source_field:
        return ()
    bindings: list[ArtifactTargetBinding] = []
    for config_ref in config_refs:
        target = resolve_standard_target(_read_config(session, config_ref), source_field)
        if target:
            bindings.append(ArtifactTargetBinding(config_ref=config_ref, target_field=target))
    return tuple(bindings)


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
            target_bindings=_target_bindings(session, threat_slot.source_field, config_refs),
        ))
    return tuple(facts)


def _collect_rule_names(config: Any) -> tuple[str, ...]:
    names: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = node.get("name")
            if isinstance(name, str) and name and name not in names:
                names.append(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(config)
    return tuple(names)


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


def build_session_facts(session: Any) -> SessionFacts:
    """把会话状态投影为不可变安全快照；缺失状态按不可用处理。"""
    enum_preview = _read_session_value(session, "enum_preview", []) or []
    mapped_sub_rules = _read_session_value(session, "mapped_sub_rules", []) or []
    decoded_data = _read_session_value(session, "decoded_data")
    available_fields, mappable_fields = _collect_field_pools(session)
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
        enum_mapping_target_fields=_collect_enum_target_fields(enum_preview),
        enum_mapping_row_count=len(enum_preview),
        existing_enum_value_count=_count_enum_values(_read_session_value(session, "last_enum_extract_result")),
        existing_threat_mapping_count=len(_read_session_value(session, "last_threat_data", []) or []),
        mapped_sub_rule_count=len(mapped_sub_rules),
        mapped_sub_rule_names=_collect_rule_names(mapped_sub_rules),
        decoded_config_rule_names=_collect_rule_names(decoded_data),
        event_annotations=_collect_event_annotations(mapped_sub_rules),
        referenceable_artifacts=_referenceable_artifacts(session, config_refs),
    )
