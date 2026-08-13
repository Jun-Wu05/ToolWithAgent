"""集中构建供 Planner 使用的不可变会话事实快照。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from web.planner_models import ConfigRef


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

    append_fields(_read_session_value(session, "decoded_fields", []) or [])
    from web.field_source import extract_log_fields_for_mapping

    classification = _read_session_value(session, "log_classification")
    raw_log_lines = _read_session_value(session, "raw_log_lines", []) or []
    append_fields(extract_log_fields_for_mapping(classification, raw_log_lines))

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
    for key in ("values", "enum_values", "data"):
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

    return SessionFacts(
        has_decoded_config=bool(decoded_data),
        has_logs=bool(original_logs or raw_log_lines),
        has_log_classification=bool(_read_session_value(session, "log_classification")),
        has_mapped_sub_rules=bool(mapped_sub_rules),
        available_config_refs=tuple(available_config_refs),
        available_fields=_collect_available_fields(session),
        enum_mapping_target_fields=_collect_enum_target_fields(enum_preview),
        enum_mapping_row_count=len(enum_preview),
        existing_enum_value_count=_count_enum_values(
            _read_session_value(session, "last_enum_extract_result")
        ),
        existing_threat_mapping_count=len(threat_data),
        mapped_sub_rule_count=len(mapped_sub_rules),
    )
