"""标准字段映射模块。

提供映射结果应用到子规则/配置的功能。
本模块独立于规则生成逻辑，可单独使用。
"""

import copy
from typing import Any

from agent.shared.event_classify import (
    EVENT_LEVEL_FIELD,
    EVENT_NAME_FIELD,
    THREAT_TYPE_FIELD,
)
from agent.shared.mapping_utils import iter_normalize_entries

# normalize entries 的 index 排除集合：系统自动生成的元字段，不参与用户字段映射
# web/action_callbacks.py 也引用此常量（原散落 4 处 literal）
# 事件名称/事件级别：事件名称标注链路写入的固定字段（PRD #124），与日志类型同为元字段
EXCLUDED_FIELD_INDICES = frozenset(
    {"original_log", "日志类型", "事件名称", "事件级别"}
)

# 映射目标黑名单：被系统固定字段机制独占的标准字段，禁止用户字段映射占用
# （issue #125 先例）。与 EXCLUDED_FIELD_INDICES 对称：前者管映射输入侧（index 排除），
# 本常量管映射目标侧（候选过滤 + 白名单降级）。威胁类型由 #173 链路独占产出
# （裸映射在平台侧是数据污染），成为第 4 个黑名单字段。
MAPPING_EXCLUDED_STANDARD_FIELDS = frozenset(
    {EVENT_NAME_FIELD, EVENT_LEVEL_FIELD, "日志类型", THREAT_TYPE_FIELD}
)


def resolve_standard_field(system_name: Any):
    """把模型返回的标准字段名确定性解析为标准字段目录记录（#177）。

    前后空白、英文字段名与规范化变体在目录可唯一定位时接受并返回该记录；
    目录外名称返回 None，由调用方降级为未匹配——对象不再默认「事件」。

    Returns:
        命中的 catalog.StandardField；无法解析时 None。
    """
    from agent.core.standard_field_catalog import get_standard_field_catalog

    if not isinstance(system_name, str) or not system_name.strip():
        return None
    return get_standard_field_catalog().lookup(system_name.strip())


def canonical_field_entity(record) -> str:
    """取目录记录「对象」列首个对象（多值逗号分隔，与 对象.xlsx 历史语义一致）。"""
    return record.objects.split(",")[0].strip()


def find_non_catalog_field_entities(config: Any) -> list[tuple[str, str, str]]:
    """扫描既有配置中非目录的 (index, field, entity) 组合（#177 诊断，不改写）。

    仅诊断 field 非空的条目：field 无法在目录解析、或 entity 与目录首个对象
    不一致即非目录组合。用于上传配置的「原样保留 + 只报告来源与数量」语义。
    """
    illegal: list[tuple[str, str, str]] = []
    for _path, _position, _owner, entry in iter_normalize_entries(
        config, require_index=False
    ):
        index = str(entry.get("index") or "")
        field_name = str(entry.get("field") or "").strip()
        entity = str(entry.get("entity") or "").strip()
        if not field_name:
            continue
        record = resolve_standard_field(field_name)
        if record is None or canonical_field_entity(record) != entity:
            illegal.append((index, field_name, entity))
    return illegal


def apply_field_mapping_to_sub_rules(
    sub_rules: list[dict[str, Any]],
    mapping_results: list[dict[str, Any]],
    corrections: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    """将标准字段映射结果应用到子规则的 normalize 条目上。

    遍历每条子规则的 normalize 条目，对匹配成功的 index 写入目录规范名称
    field + 目录对象 entity（#177：标准字段目录是对象归属 SSOT）；目录外
    名称与显式未匹配行一律降级清空（field/entity/sim/core=None），避免
    重新映射时残留旧映射或写入非法组合。

    Args:
        sub_rules: 子规则列表（会被深拷贝，不修改原始数据）。
        mapping_results: 映射结果列表，格式：
            [{"rule_name": str, "mappings": [
                {"原始字段名": str, "系统属性名称": str, "匹配状态": str}
            ]}]
        corrections: 🔮 预留扩展点 — 用户手动修正映射。
            格式: {rule_name: {原始字段名: {"系统属性名称": str}}}

    Returns:
        修改后的子规则列表（深拷贝）。
    """

    # 构建 rule_name → {原始字段名: mapping_dict} 的查找表
    rule_mappings: dict[str, dict[str, dict]] = {}
    for mr in mapping_results:
        rn: str = mr.get("rule_name", "")
        field_map: dict[str, dict] = {}
        for m in mr.get("mappings", []):
            orig = m.get("原始字段名", "")
            if orig:
                field_map[orig] = m
        rule_mappings[rn] = field_map

    # 深拷贝子规则，不修改原始数据
    result_rules: list[dict[str, Any]] = copy.deepcopy(sub_rules)

    for rule in result_rules:
        rule_name = rule.get("name", "")
        field_map = rule_mappings.get(rule_name, {})

        # 🔮 预留：应用用户手动修正
        if corrections and rule_name in corrections:
            for orig_field, correction in corrections[rule_name].items():
                if orig_field in field_map:
                    field_map[orig_field] = {
                        "原始字段名": orig_field,
                        "系统属性名称": correction.get("系统属性名称", ""),
                        "匹配状态": "用户修正",
                    }

        for entry in rule.get("normalize", []):
            idx = entry.get("index", "")
            if not idx or idx in EXCLUDED_FIELD_INDICES:
                continue

            mapping = field_map.get(idx)
            if not mapping:
                continue

            match_status = mapping.get("匹配状态", "")
            system_prop = mapping.get("系统属性名称", "")

            record = None
            if "匹配成功" in match_status and system_prop and system_prop != "未匹配":
                record = resolve_standard_field(system_prop)
            if record is not None:
                entry["field"] = record.system_property_name
                entry["entity"] = canonical_field_entity(record)
                entry["sim"] = True
                entry["core"] = False
            else:
                entry["field"] = None
                entry["entity"] = None
                entry["sim"] = None
                entry["core"] = None

    return result_rules


def apply_field_mapping_to_config(
    config: Any,
    mappings: list[dict[str, Any]],
) -> Any:
    """把字段映射结果递归应用到配置的所有 normalize 条目。

    遍历范围与 _extract_normalize_indexes 一致（递归 dict/list），对匹配 index 且
    「匹配成功」且原 field 为空的条目写入目录规范名称 field + 目录对象 entity
    （#177）；目录外名称不写入（条目保持原样，field 仍为空）。已有非空 field
    的外部映射、未匹配、未匹配状态，以及 EXCLUDED_FIELD_INDICES 中的元字段
    保持不变（上传规则保留语义）。不修改原对象。
    """
    field_map: dict[str, dict] = {
        m.get("原始字段名", ""): m for m in mappings if m.get("原始字段名", "")
    }
    updated = copy.deepcopy(config)

    def _apply(obj: Any) -> None:
        if isinstance(obj, dict):
            normalize = obj.get("normalize")
            if isinstance(normalize, list):
                for entry in normalize:
                    if not isinstance(entry, dict):
                        continue
                    idx = entry.get("index", "")
                    if not idx or idx in EXCLUDED_FIELD_INDICES:
                        continue
                    if str(entry.get("field") or "").strip():
                        continue
                    mapping = field_map.get(idx)
                    if not mapping:
                        continue
                    match_status = mapping.get("匹配状态", "")
                    system_prop = mapping.get("系统属性名称", "")
                    record = None
                    if "匹配成功" in match_status and system_prop and system_prop != "未匹配":
                        record = resolve_standard_field(system_prop)
                    if record is not None:
                        entry["field"] = record.system_property_name
                        entry["entity"] = canonical_field_entity(record)
                        entry["sim"] = True
                        entry["core"] = False
            for value in obj.values():
                _apply(value)
        elif isinstance(obj, list):
            for item in obj:
                _apply(item)

    _apply(updated)
    return updated
