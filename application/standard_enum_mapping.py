"""标准枚举自动映射（#189）：值画像、第二阶段归类编排与硬校验。

职责边界：代码负责值的发现、约束、校验与编排；LLM 只对代码产出的去重值
画像做一次受约束的语义归类（orgValue → 白名单标准值）。任一硬校验失败即
局部失败关闭：该画像零写入，对应子规则内该字段名映射降级「未匹配」。
写回（mappings + 外层 value）由 agent.shared.mapping_utils.apply_enum_outcomes 承担。
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from agent.core.standard_field_catalog import (
    ENUM_UNIQUE_VALUE_LIMIT,
    EnumMappingPolicy,
)
from agent.shared.logger import get_logger
from agent.shared.mapping_utils import iter_normalize_entries

logger = get_logger("standard_enum_mapping")

ModelCaller = Callable[[str], Awaitable[str]]
ProfileKey = tuple[str, ...]
"""画像键：(owner 节点结构路径…, normalize index)，深拷贝前后保持稳定。"""

_EXCLUDED_INDEXES = frozenset({"original_log", "日志类型", "事件名称", "事件级别"})
_MISSING = object()


@dataclass
class FieldValueProfile:
    """一个「子规则/配置节点 × 原始字段」的值画像。"""

    owner: str
    field: str
    values: dict[str, int] = field(default_factory=dict)
    empty_count: int = 0
    scanned_lines: int = 0
    hit_lines: int = 0
    source: str = "full-logs"
    status: str = "ok"
    reject_reason: str = ""


@dataclass
class EnumProfileOutcome:
    """一个枚举画像的第二阶段结果（成功写入项或稳定拒绝原因）。"""

    key: ProfileKey
    profile: FieldValueProfile
    policy: EnumMappingPolicy
    selection_source: str
    mappings: tuple[dict[str, str], ...] = ()
    default_mapped_count: int = 0
    reject_reason: str = ""


def iter_normalize_owners(
    node: Any,
) -> Iterator[tuple[ProfileKey, str, dict[str, Any], dict[str, Any]]]:
    """递归产出 ((路径…, index), 展示名, owner 节点, normalize 条目)；元字段跳过。

    遍历自 agent.shared.mapping_utils.iter_normalize_entries 收口（#313）：
    画像键保持纯 str 约定（dict 键与 list 位置都 str 化），与
    mapping_utils.apply_enum_outcomes 共用同一遍历实现，不再人工保持同步。
    """
    for owner_path, _position, owner, entry in iter_normalize_entries(
        node, excluded_indexes=_EXCLUDED_INDEXES
    ):
        display = str(
            owner.get("name")
            or "/".join(str(segment) for segment in owner_path)
            or "config"
        )
        index = str(entry.get("index") or "").strip()
        yield (
            *tuple(str(segment) for segment in owner_path),
            index,
        ), display, dict(owner), entry


def _accept_value(profile: FieldValueProfile, raw: Any) -> None:
    """按 value_to_str 语义累计一个字段值；复合值或第 11 个唯一值整画像拒绝。"""
    if profile.status != "ok":
        return
    if isinstance(raw, (dict, list)):
        profile.status = "rejected"
        profile.reject_reason = "字段值包含数组或对象，拒绝整个画像"
        return
    if raw is None or (isinstance(raw, str) and raw == ""):
        profile.empty_count += 1
        return
    from agent.tools.rule_generator.utils import value_to_str

    text = value_to_str(raw)
    if text == "":
        profile.empty_count += 1
        return
    profile.values[text] = profile.values.get(text, 0) + 1
    if len(profile.values) > ENUM_UNIQUE_VALUE_LIMIT:
        profile.status = "rejected"
        profile.reject_reason = f"唯一值超过 {ENUM_UNIQUE_VALUE_LIMIT} 个上限，拒绝整个画像"


def build_value_profiles_from_config(config: Any) -> dict[ProfileKey, FieldValueProfile]:
    """配置样本模式：从既有 normalize result 读取值（标记 config-sample）。"""
    profiles: dict[ProfileKey, FieldValueProfile] = {}
    for key, display, _owner, entry in iter_normalize_owners(config):
        profile = FieldValueProfile(owner=display, field=key[-1], source="config-sample")
        samples = entry.get("result") or []
        profile.scanned_lines = len(samples)
        for raw in samples:
            _accept_value(profile, raw)
        profile.hit_lines = profile.scanned_lines - profile.empty_count
        profiles[key] = profile
    return profiles


def _parser_logtype(owner: dict[str, Any]) -> str:
    """从 addFields 过滤或日志类型条目取子规则的 logtype。"""
    parser = owner.get("parser") or {}
    for item in parser.get("filter") or []:
        if isinstance(item, dict) and item.get("name") == "addFields":
            logtype = str((item.get("fields") or {}).get("日志类型") or "")
            if logtype:
                return logtype
    for entry in owner.get("normalize") or []:
        if isinstance(entry, dict) and entry.get("index") == "日志类型":
            result = entry.get("result")
            if isinstance(result, list) and result:
                return str(result[0] or "")
    return ""


def _parser_delimit(owner: dict[str, Any]) -> str:
    """把 parser.delimit 的转义形式还原为拆分器语义名。"""
    delimit = str((owner.get("parser") or {}).get("delimit") or " ")
    if delimit in ("\\s", "\\s+"):
        return "space"
    if delimit == "\\t":
        return "tab"
    return delimit


def iter_rule_field_values(
    owner: dict[str, Any], target: str, raw_log_lines: list[str],
    classification: Mapping[str, Any] | None = None, rule_position: int | None = None,
    config_samples: list[Any] | None = None,
) -> tuple[str, Iterator[tuple[int | None, bool, Any]]]:
    """Return sample source and (original line number, field present, value) rows.

    Missing/invalid rows remain in the iterator so profile scan counts retain
    their original meaning. Config samples have no original log line number.
    """
    source, records = iter_rule_records(owner, raw_log_lines, classification, rule_position)
    if source == "full-logs":
        return source, ((number, (value := _lookup_member_value(record, target)) is not _MISSING, value)
                        for number, record in records)
    if config_samples is None:
        config_samples = next((entry.get("result") or [] for entry in owner.get("normalize", [])
                               if isinstance(entry, dict) and entry.get("index") == target), [])
    return "config-sample", ((None, True, value) for value in config_samples)


def iter_rule_records(
    owner: dict[str, Any], raw_log_lines: list[str],
    classification: Mapping[str, Any] | None = None, rule_position: int | None = None,
) -> tuple[str, Iterator[tuple[int, Mapping[str, Any]]]]:
    """Parse each relevant log line once for all fields of a sub-rule."""
    lines = [(number, str(line)) for number, line in enumerate(raw_log_lines or [], 1)
             if str(line).strip()]
    classification = dict(classification or {})
    logtype = _parser_logtype(owner)
    details = [str(detail.get("logtype") or "")
               for detail in (classification.get("classification_details") or []) if isinstance(detail, dict)]
    if not logtype and rule_position is not None and rule_position < len(details):
        logtype = details[rule_position]
    parser = owner.get("parser") or {}
    parser_name = str(parser.get("name") or "")
    pattern = None
    try:
        if classification.get("feature_identifier"):
            pattern = re.compile(str(classification["feature_identifier"]))
    except re.error:
        pass
    body_group = int(classification.get("feature_body_group", 1) or 1)
    value_group = int(classification.get("feature_value_group", 2) or 2)
    if parser_name == "json" and pattern is not None and logtype:
        matches = [(number, line, match) for number, line in lines if (match := pattern.search(line))
                   and len(match.groups()) >= max(body_group, value_group)
                   and match.group(value_group) == logtype]
        if matches:
            def json_values():
                for number, line, match in matches:
                    try:
                        body = json.loads(match.group(body_group) or line)
                        yield number, body
                    except (json.JSONDecodeError, ValueError):
                        yield number, {}
            return "full-logs", json_values()
    elif parser_name in ("delimitWithKeyMap", "delimit"):
        from agent.tools.rule_generator.utils import extract_kv_pairs
        member_lines = [(number, line) for number, line in lines if logtype and logtype in line] or lines
        def kv_values():
            for number, line in member_lines:
                pairs = dict(extract_kv_pairs(line, _parser_delimit(owner), str(parser.get("tab") or "=")))
                yield number, pairs
        return "full-logs", kv_values()
    return "config-sample", iter(())


def build_value_profiles_from_logs(
    sub_rules: Any, raw_log_lines: list[str], classification: Mapping[str, Any] | None = None,
) -> dict[ProfileKey, FieldValueProfile]:
    """Scan each rule using the shared value reader; retain the 10-value policy."""
    profiles: dict[ProfileKey, FieldValueProfile] = {}
    groups: dict[ProfileKey, list[tuple[ProfileKey, str, dict[str, Any], dict[str, Any]]]] = {}
    for key, display, owner, entry in iter_normalize_owners(sub_rules):
        groups.setdefault(key[:-1], []).append((key, display, owner, entry))
    for path, members in groups.items():
        # Legacy per-field loop overwrote duplicate normalize indexes with the last entry.
        members = list({member[0]: member for member in members}.values())
        position = path[-1] if path else ""
        source, records = iter_rule_records(members[0][2], raw_log_lines, classification,
                                            int(position) if position.isdigit() else None)
        for key, display, _owner, _entry in members:
            profiles[key] = FieldValueProfile(owner=display, field=key[-1], source=source)
        if source == "full-logs":
            for _number, record in records:
                for key, _display, _owner, _entry in members:
                    profile = profiles[key]
                    profile.scanned_lines += 1
                    value = _lookup_member_value(record, key[-1])
                    if value is not _MISSING:
                        profile.hit_lines += 1
                        _accept_value(profile, value)
        else:
            for key, _display, _owner, entry in members:
                profile = profiles[key]
                for value in entry.get("result") or []:
                    profile.scanned_lines += 1
                    _accept_value(profile, value)
                profile.hit_lines = profile.scanned_lines - profile.empty_count
    return profiles


def _lookup_member_value(record: Mapping[str, Any], target: str) -> Any:
    """按 normalize 生成语义取字段值：直接 key 或一级嵌套 parent.child。"""
    if not isinstance(record, Mapping):
        return _MISSING
    if target in record:
        return record[target]
    head, _, child = target.partition(".")
    parent = record.get(head)
    if isinstance(parent, Mapping) and child:
        return parent.get(child, _MISSING)
    return _MISSING


def build_review_prompt(profile: FieldValueProfile, policy: EnumMappingPolicy) -> str:
    """构造第二阶段用户输入：复核指令 + 值画像 + 白名单 + 默认值。"""
    from agent.prompts import load_enum_value_review_prompt

    values_payload = [
        {"orgValue": value, "count": count} for value, count in profile.values.items()
    ]
    return (
        f"{load_enum_value_review_prompt()}\n\n"
        f"## 目标标准字段\n{policy.system_property_name}（英文: {policy.field_name}）\n"
        f"## 日志类型/规则\n{profile.owner}\n"
        f"## 原始字段\n{profile.field}\n"
        f"## 唯一非空值（{len(values_payload)} 个，逐字保留）\n"
        f"{json.dumps(values_payload, ensure_ascii=False)}\n"
        f"## 白名单（系统属性名称只能从中选择）\n"
        f"{json.dumps(list(policy.whitelist), ensure_ascii=False)}\n"
        f"## 默认值（无法归类的兼容值选它）\n{policy.default_value}\n"
    )


async def review_enum_profile(
    key: ProfileKey,
    profile: FieldValueProfile,
    policy: EnumMappingPolicy,
    selection_source: str,
    call_model: ModelCaller,
) -> EnumProfileOutcome:
    """执行第二阶段归类并做结构性硬校验（不能缺语义，2026-09-28 契约调整）。

    值无法归类（含模型输出「未匹配」）一律按默认值兜底写入；仅结构性失败
    （画像拒绝、集合不一致、白名单外、调用失败）才整画像拒绝、零写入。
    空画像（无非空值）不调用模型、无 mappings、不算失败。
    """
    outcome = EnumProfileOutcome(
        key=key, profile=profile, policy=policy, selection_source=selection_source
    )
    if profile.status != "ok":
        outcome.reject_reason = profile.reject_reason or "画像校验失败"
        return outcome
    if not profile.values:
        return outcome

    from application.parsing import parse_json_mapping_result

    prompt = build_review_prompt(profile, policy)
    rows: list[dict[str, Any]] = []
    last_error = ""
    for _attempt in range(2):  # 复用既有“一次重试”边界
        try:
            rows = parse_json_mapping_result(await call_model(prompt))
            if rows:
                break
            last_error = "模型返回空结果"
        except Exception as error:  # noqa: BLE001 - 二阶段失败按局部失败关闭处理
            last_error = f"{type(error).__name__}: {error}"
    if not rows:
        outcome.reject_reason = f"第二阶段调用失败（{last_error}）"
        return outcome

    classified: dict[str, str] = {}
    for row in rows:
        org_value = str(row.get("原始字段名") or "")
        if not org_value or org_value in classified:
            outcome.reject_reason = "输出原值缺失或重复"
            return outcome
        mapping_value = str(row.get("系统属性名称") or "")
        if not mapping_value or mapping_value == "未匹配":
            mapping_value = policy.default_value
        classified[org_value] = mapping_value

    if set(classified) != set(profile.values):
        outcome.reject_reason = "输出原值集合与画像不一致（缺失或幻觉新增）"
        return outcome
    if any(value not in policy.whitelist for value in classified.values()):
        outcome.reject_reason = "存在白名单外的 mappingValue"
        return outcome

    outcome.mappings = tuple(
        {"mappingType": "EQUAL", "orgValue": value, "mappingValue": classified[value]}
        for value in profile.values
    )
    outcome.default_mapped_count = sum(
        1 for item in outcome.mappings if item["mappingValue"] == policy.default_value
    )
    return outcome


async def run_enum_review_stage(
    mapping_rows: list[dict[str, Any]],
    *,
    profiles_sub: dict[ProfileKey, FieldValueProfile],
    profiles_config: dict[ProfileKey, FieldValueProfile],
    resolved_enum_fields: Mapping[str, tuple[str, str]],
    call_model: ModelCaller,
) -> tuple[dict[ProfileKey, EnumProfileOutcome], dict[ProfileKey, EnumProfileOutcome]]:
    """对冲突裁决后的映射行执行完整第二阶段；就地做全局降级并返回两份结果。

    策略表校验失败或无目标命中时返回空结果且不改 ``mapping_rows``。
    跨子规则字段一致性（2026-09-28 契约调整）：字段名映射结果全局统一，
    仅当某字段**全部画像结构性失败**（无任何成功写入）时才把全局行降级为
    「未匹配」；成功与失败并存的字段保持映射，各子规则写各自的值映射。
    """
    from agent.core.standard_field_catalog import enum_auto_mapping_policies

    try:
        policies = enum_auto_mapping_policies()
    except ValueError as error:
        logger.warning("[ENUM_MAPPING] 枚举策略表校验失败，自动枚举映射停用: %s", error)
        return {}, {}

    enum_field_targets: dict[str, str] = {}
    for row in mapping_rows:
        target = str(row.get("系统属性名称") or "")
        if "匹配成功" in str(row.get("匹配状态") or "") and target in policies:
            enum_field_targets[str(row.get("原始字段名") or "")] = target
    if not enum_field_targets:
        return {}, {}

    selection_sources = {
        field: source for field, (_target, source) in resolved_enum_fields.items()
    }
    outcomes_sub: dict[ProfileKey, EnumProfileOutcome] = {}
    outcomes_config: dict[ProfileKey, EnumProfileOutcome] = {}
    for profiles, sink in ((profiles_sub, outcomes_sub), (profiles_config, outcomes_config)):
        for key, profile in profiles.items():
            target = enum_field_targets.get(profile.field)
            if target is None:
                continue
            sink[key] = await review_enum_profile(
                key, profile, policies[target],
                selection_sources.get(profile.field, "llm"), call_model,
            )

    ok_fields = {
        outcome.profile.field
        for outcome in (*outcomes_sub.values(), *outcomes_config.values())
        if outcome.mappings
    }
    failed_fields = {
        outcome.profile.field
        for outcome in (*outcomes_sub.values(), *outcomes_config.values())
        if outcome.reject_reason
    }
    for row in mapping_rows:
        field = str(row.get("原始字段名") or "")
        if (
            field in failed_fields
            and field not in ok_fields
            and str(row.get("系统属性名称") or "") in policies
        ):
            row["系统属性名称"] = "未匹配"
            row["匹配状态"] = "未匹配"
    return outcomes_sub, outcomes_config


def summarize_enum_outcomes(outcomes: dict[ProfileKey, EnumProfileOutcome]) -> str:
    """生成画像级执行报告日志与用户可见汇总；无结果时返回空串。"""
    if not outcomes:
        return ""
    success = [item for item in outcomes.values() if item.mappings]
    for item in outcomes.values():
        profile = item.profile
        logger.info(
            "[ENUM_MAPPING_REPORT] owner=%s field=%s target=%s source_data=%s "
            "selection=%s scanned=%s hit=%s unique=%s empty=%s written=%s "
            "default_mapped=%s status=%s reason=%s",
            profile.owner, profile.field, item.policy.system_property_name,
            profile.source, item.selection_source, profile.scanned_lines,
            profile.hit_lines, len(profile.values), profile.empty_count,
            len(item.mappings), item.default_mapped_count,
            "ok" if item.mappings else ("rejected" if item.reject_reason else "empty"),
            item.reject_reason,
        )
    parts = [f"枚举值映射 {len(success)} 个画像成功"]
    rejected = sum(1 for item in outcomes.values() if item.reject_reason)
    if rejected:
        parts.append(f"{rejected} 个画像未通过结构校验已全局未匹配")
    return "；".join(parts)


__all__ = [
    "EnumProfileOutcome",
    "FieldValueProfile",
    "build_review_prompt",
    "build_value_profiles_from_config",
    "build_value_profiles_from_logs",
    "iter_rule_field_values",
    "iter_normalize_owners",
    "review_enum_profile",
    "run_enum_review_stage",
    "summarize_enum_outcomes",
]
