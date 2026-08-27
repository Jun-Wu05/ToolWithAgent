"""集中构建供 Planner 使用的不可变会话事实快照。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.artifact_targets import resolve_standard_target
from contracts.planner_models import ConfigRef
from contracts.session_artifacts import (
    ArtifactTargetBinding,
    EnumArtifactSlot,
    ReferenceableArtifactFact,
    ThreatArtifactSlot,
)
from agent.shared.event_classify import EVENT_NAME_LEVEL_BINDING, read_entity_event_name


class EventAnnotationFact(BaseModel):
    """一条子规则的事件标注事实（未标注时 event_name/event_level 为空串）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_name: str = Field(min_length=1)
    event_name: str = ""
    event_level: str = ""


class SessionFacts(BaseModel):
    """仅暴露意图理解所需的状态，不泄露路径、密钥或原始内容。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    has_decoded_config: bool = False
    has_logs: bool = False
    has_log_classification: bool = False
    has_mapped_sub_rules: bool = False
    available_config_refs: tuple[ConfigRef, ...] = ()
    available_fields: tuple[str, ...] = ()
    enum_mapping_target_fields: tuple[str, ...] = ()
    enum_mapping_row_count: int = Field(default=0, ge=0)
    existing_enum_value_count: int = Field(default=0, ge=0)
    existing_threat_mapping_count: int = Field(default=0, ge=0)
    mapped_sub_rule_count: int = Field(default=0, ge=0)
    """映射后子规则数量。"""
    mapped_sub_rule_names: tuple[str, ...] = ()
    """子规则名单（entity name，去重保序），供字段调整寻址（#126）。"""
    decoded_config_rule_names: tuple[str, ...] = ()
    """上传配置的 entity 名单，供字段调整寻址（#126）。"""
    event_annotations: tuple[EventAnnotationFact, ...] = ()
    """各子规则的事件名称/级别标注（mapped_sub_rules 投影，#149 信息型问答事实）。"""
    referenceable_artifacts: tuple[ReferenceableArtifactFact, ...] = ()


def _read_session_value(session: Any, key: str, default: Any = None) -> Any:
    """兼容 SessionState 与测试字典，且不把兼容逻辑扩散到其他模块。"""
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _collect_available_fields(session: Any) -> tuple[str, ...]:
    """从唯一位置汇总可用字段，去重同时保留字段首次出现的顺序。"""
    ordered_fields: list[str] = []
    seen_fields: set[str] = set()

    # 系统自动生成的元字段（original_log、日志类型）不参与用户字段映射，在汇合点统一排除，
    # 覆盖 decoded_fields 与 mapped_sub_rules 等 3 个来源（含已过滤的日志来源，幂等）。
    from agent.tools.rule_generator.field_mapping import EXCLUDED_FIELD_INDICES
    from web.field_source import extract_log_fields_for_mapping

    def append_fields(values: Any) -> None:
        """追加合法字段；重复值不改变首次出现位置；跳过系统元字段。"""
        for item in values or []:
            field_name = str(item).strip()
            if (
                field_name
                and field_name not in seen_fields
                and field_name not in EXCLUDED_FIELD_INDICES
            ):
                seen_fields.add(field_name)
                ordered_fields.append(field_name)

    classification = _read_session_value(session, "log_classification")
    raw_log_lines = _read_session_value(session, "raw_log_lines", []) or []
    log_fields = extract_log_fields_for_mapping(classification, raw_log_lines)
    if log_fields:
        # 有真实日志字段时 Excel 列头不参与映射（回归 #78）；
        # decoded_fields 仅作为无日志字段时的回退（Base64/TXT 配置上传场景）。
        append_fields(log_fields)
    else:
        append_fields(_read_session_value(session, "decoded_fields", []) or [])

    for sub_rule in _read_session_value(session, "mapped_sub_rules", []) or []:
        if not isinstance(sub_rule, Mapping):
            continue
        for normalization in sub_rule.get("normalize", []) or []:
            if not isinstance(normalization, Mapping):
                continue
            append_fields(normalization.get(key) for key in ("index", "field"))
    return tuple(ordered_fields)

def _collect_enum_target_fields(enum_preview: Any) -> tuple[str, ...]:
    """从映射表结构读取目标字段，禁止根据用户原文或文件名猜测。"""
    target_fields: set[str] = set()
    for row in enum_preview or []:
        if not isinstance(row, Mapping):
            continue
        value = row.get("目标字段")
        if value is not None and str(value).strip():
            target_fields.add(str(value).strip())
    return tuple(sorted(target_fields))


def _count_enum_values(enum_result: Any) -> int:
    """仅提取旧结果的数量事实，不把旧值暴露为本次步骤输入。"""
    if not isinstance(enum_result, Mapping):
        return 0
    for key in ("value", "values", "enum_values", "data"):
        values = enum_result.get(key)
        if isinstance(values, (list, tuple, set)):
            return len(values)
    return 0


def _count_normalize_entries(value: Any) -> int:
    """递归统计配置中的 normalize 条目，用结构事实判断配置是否可填充。"""
    if isinstance(value, Mapping):
        normalize = value.get("normalize")
        own_count = len(normalize) if isinstance(normalize, list) else 0
        return own_count + sum(_count_normalize_entries(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_normalize_entries(item) for item in value)
    return 0


def _read_config(session: Any, config_ref: ConfigRef) -> Any:
    """按公共配置引用读取真实结构，不在事实层引入适配器依赖。"""
    key = "decoded_data" if config_ref == "session.decoded_config" else "mapped_sub_rules"
    return _read_session_value(session, key)


def _target_bindings(
    session: Any,
    source_field: str | None,
    available_config_refs: tuple[ConfigRef, ...],
) -> tuple[ArtifactTargetBinding, ...]:
    """为来源字段计算逐配置绑定；无法唯一确定时不向 Planner 暴露猜测。"""
    if not source_field:
        return ()
    bindings: list[ArtifactTargetBinding] = []
    for config_ref in available_config_refs:
        target_field = resolve_standard_target(_read_config(session, config_ref), source_field)
        if target_field:
            bindings.append(
                ArtifactTargetBinding(config_ref=config_ref, target_field=target_field)
            )
    return tuple(bindings)


def _referenceable_artifacts(
    session: Any,
    available_config_refs: tuple[ConfigRef, ...],
) -> tuple[ReferenceableArtifactFact, ...]:
    """只投影通过类型校验的新产物槽；旧 last_* 绝不自动升级。"""
    facts: list[ReferenceableArtifactFact] = []
    raw_enum = _read_session_value(session, "latest_enum_artifact")
    try:
        enum_slot = (
            raw_enum
            if isinstance(raw_enum, EnumArtifactSlot)
            else EnumArtifactSlot.model_validate(raw_enum)
            if raw_enum is not None
            else None
        )
    except (TypeError, ValueError):
        enum_slot = None
    if enum_slot is not None:
        facts.append(
            ReferenceableArtifactFact(
                source_ref="session.artifacts.enum_values",
                artifact_type="enum_values",
                source_field=enum_slot.source_field,
                item_count=enum_slot.artifact.item_count,
                target_bindings=_target_bindings(
                    session,
                    enum_slot.source_field,
                    available_config_refs,
                ),
            )
        )

    raw_threat = _read_session_value(session, "latest_threat_artifact")
    try:
        threat_slot = (
            raw_threat
            if isinstance(raw_threat, ThreatArtifactSlot)
            else ThreatArtifactSlot.model_validate(raw_threat)
            if raw_threat is not None
            else None
        )
    except (TypeError, ValueError):
        threat_slot = None
    if threat_slot is not None:
        facts.append(
            ReferenceableArtifactFact(
                source_ref="session.artifacts.threat_mapping",
                artifact_type="threat_mapping",
                source_field=threat_slot.source_field,
                item_count=threat_slot.artifact.item_count,
                target_bindings=_target_bindings(
                    session,
                    threat_slot.source_field,
                    available_config_refs,
                ),
            )
        )
    return tuple(facts)

def _collect_rule_names(config: Any) -> tuple[str, ...]:
    """递归收集配置中全部 entity 的 name（去重保序，#126 寻址事实）。"""
    names: list[str] = []

    def _walk(node: Any) -> None:
        """递归遍历配置，收集各 entity 的 name。"""
        if isinstance(node, dict):
            name = node.get("name")
            if isinstance(name, str) and name and name not in names:
                names.append(name)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(config)
    return tuple(names)


def _collect_event_annotations(config: Any) -> tuple[EventAnnotationFact, ...]:
    """按子规则投影事件名称/级别标注（#149）。

    未标注子规则也占位（event_name 为空串），信息型问答才能报出全量名单；
    事件级别由 21 名绑定表确定性推导，与联动写入语义一致。
    """
    facts: list[EventAnnotationFact] = []
    for entity in config or []:
        if not isinstance(entity, Mapping):
            continue
        name = entity.get("name")
        if not (isinstance(name, str) and name):
            continue
        event_name = read_entity_event_name(entity) or ""
        facts.append(
            EventAnnotationFact(
                rule_name=name,
                event_name=event_name,
                event_level=EVENT_NAME_LEVEL_BINDING.get(event_name, ""),
            )
        )
    return tuple(facts)


def build_session_facts(session: Any) -> SessionFacts:
    """把会话状态投影为不可变安全快照；缺失状态按“不可用”处理。"""
    enum_preview = _read_session_value(session, "enum_preview", []) or []
    mapped_sub_rules = _read_session_value(session, "mapped_sub_rules", []) or []
    original_logs = _read_session_value(session, "original_log", []) or []
    raw_log_lines = _read_session_value(session, "raw_log_lines", []) or []
    threat_data = _read_session_value(session, "last_threat_data", []) or []
    decoded_data = _read_session_value(session, "decoded_data")
    decoded_normalize_count = _count_normalize_entries(decoded_data)
    mapped_normalize_count = _count_normalize_entries(mapped_sub_rules)
    available_config_refs: list[ConfigRef] = []
    if decoded_normalize_count:
        available_config_refs.append("session.decoded_config")
    if mapped_normalize_count:
        available_config_refs.append("session.mapped_sub_rules")

    config_refs = tuple(available_config_refs)
    return SessionFacts(
        has_decoded_config=bool(decoded_data),
        has_logs=bool(original_logs or raw_log_lines),
        has_log_classification=bool(_read_session_value(session, "log_classification")),
        has_mapped_sub_rules=bool(mapped_sub_rules),
        available_config_refs=config_refs,
        available_fields=_collect_available_fields(session),
        enum_mapping_target_fields=_collect_enum_target_fields(enum_preview),
        enum_mapping_row_count=len(enum_preview),
        existing_enum_value_count=_count_enum_values(
            _read_session_value(session, "last_enum_extract_result")
        ),
        existing_threat_mapping_count=len(threat_data),
        mapped_sub_rule_count=len(mapped_sub_rules),
        mapped_sub_rule_names=_collect_rule_names(mapped_sub_rules),
        decoded_config_rule_names=_collect_rule_names(decoded_data),
        event_annotations=_collect_event_annotations(mapped_sub_rules),
        referenceable_artifacts=_referenceable_artifacts(session, config_refs),
    )
