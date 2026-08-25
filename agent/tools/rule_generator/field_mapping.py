"""标准字段映射模块。

提供子规则字段映射信息的提取和映射结果应用功能。
本模块独立于规则生成逻辑，可单独使用。
"""

import copy
from typing import Any

from agent.shared.event_classify import EVENT_LEVEL_FIELD, EVENT_NAME_FIELD

# normalize entries 的 index 排除集合：系统自动生成的元字段，不参与用户字段映射
# web/action_callbacks.py 也引用此常量（原散落 4 处 literal）
# 事件名称/事件级别：事件名称标注链路写入的固定字段（PRD #124），与日志类型同为元字段
EXCLUDED_FIELD_INDICES = frozenset(
    {"original_log", "日志类型", "事件名称", "事件级别"}
)

# 映射目标黑名单：被系统固定字段机制独占的标准字段，禁止用户字段映射占用
# （issue #125）。与 EXCLUDED_FIELD_INDICES 对称：前者管映射输入侧（index 排除），
# 本常量管映射目标侧（候选过滤 + 白名单降级）。后续新增固定枚举字段只加一个名字。
MAPPING_EXCLUDED_STANDARD_FIELDS = frozenset(
    {EVENT_NAME_FIELD, EVENT_LEVEL_FIELD, "日志类型"}
)


def extract_sub_rule_mapping_info(sub_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从子规则列表中提取字段映射所需信息（字段列表 + 原始日志样本）。

    对每条子规则，提取 normalize 条目的 index 列表和 sample（原始日志），
    供 Agent/LLM 进行标准字段映射分析。

    Args:
        sub_rules: generate_sub_rules() 输出的子规则列表。

    Returns:
        [{"rule_name": str, "fields": [str], "sample_log": str}, ...]
    """
    result: list[dict[str, Any]] = []
    for rule in sub_rules:
        rule_name: str = rule.get("name", "")
        sample_log: str = rule.get("sample", "")

        # 提取 normalize entries 的 index（排除元字段）
        fields: list[str] = []
        for entry in rule.get("normalize", []):
            idx = entry.get("index", "")
            if idx and idx not in EXCLUDED_FIELD_INDICES:
                fields.append(idx)

        result.append({
            "rule_name": rule_name,
            "fields": fields,
            "sample_log": sample_log,
        })
    return result


def apply_field_mapping_to_sub_rules(
    sub_rules: list[dict[str, Any]],
    mapping_results: list[dict[str, Any]],
    object_entity_map: dict[str, str] | None = None,
    corrections: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    """将标准字段映射结果应用到子规则的 normalize 条目上。

    遍历每条子规则的 normalize 条目，对匹配的 index 设置
    field（标准字段名）、entity（对象）、sim（True）、core（False）。

    Args:
        sub_rules: 子规则列表（会被深拷贝，不修改原始数据）。
        mapping_results: 映射结果列表，格式：
            [{"rule_name": str, "mappings": [
                {"原始字段名": str, "系统属性名称": str, "匹配状态": str}
            ]}]
        object_entity_map: 系统属性名称→对象 的映射（从 对象.xlsx 读取）。
            若为 None，entity 默认设为 "事件"。
        corrections: 🔮 预留扩展点 — 用户手动修正映射。
            格式: {rule_name: {原始字段名: {"系统属性名称": str, "对象": str}}}

    Returns:
        修改后的子规则列表（深拷贝）。
    """
    if object_entity_map is None:
        object_entity_map = {}

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

            if "匹配成功" in match_status and system_prop and system_prop != "未匹配":
                entry["field"] = system_prop
                entry["entity"] = object_entity_map.get(system_prop, "事件")
                entry["sim"] = True
                entry["core"] = False

    return result_rules


def apply_field_mapping_to_config(
    config: Any,
    mappings: list[dict[str, Any]],
    object_entity_map: dict[str, str] | None = None,
) -> Any:
    """把字段映射结果递归应用到配置的所有 normalize 条目。

    遍历范围与 _extract_normalize_indexes 一致（递归 dict/list），对匹配 index 且
    「匹配成功」的条目设置 field（标准字段名）、entity（对象）、sim=True、core=False。
    未匹配、未匹配状态、以及 EXCLUDED_FIELD_INDICES 中的元字段保持不变。不修改原对象。
    """
    if object_entity_map is None:
        object_entity_map = {}

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
                    mapping = field_map.get(idx)
                    if not mapping:
                        continue
                    match_status = mapping.get("匹配状态", "")
                    system_prop = mapping.get("系统属性名称", "")
                    if "匹配成功" in match_status and system_prop and system_prop != "未匹配":
                        entry["field"] = system_prop
                        entry["entity"] = object_entity_map.get(system_prop, "事件")
                        entry["sim"] = True
                        entry["core"] = False
            for value in obj.values():
                _apply(value)
        elif isinstance(obj, list):
            for item in obj:
                _apply(item)

    _apply(updated)
    return updated


def apply_enum_fill_to_sub_rules(
    sub_rules: list[dict[str, Any]],
    mapping_table: dict[str, list[dict]],
    target_field: str = None,
) -> list[dict[str, Any]]:
    """对子规则列表应用枚举/威胁填充（mappings 追加）。

    向后兼容包装：委托 agent.shared.mapping_utils.apply_fill_to_sub_rules。
    威胁填充和枚举填充在 apply 层面是同一操作，统一到共享函数消除重复。

    Args:
        sub_rules: 子规则列表（generate_sub_rules 输出，字段映射后含 field 标注）
        mapping_table: {字段名: [{mappingType, orgValue, mappingValue}, ...]}
        target_field: 可选，只填充该字段；None 表示填充 mapping_table 里所有字段

    Returns:
        深拷贝后的 sub_rules，匹配的 normalize 项已追加 mappings
    """
    from agent.shared.mapping_utils import apply_fill_to_sub_rules
    return apply_fill_to_sub_rules(sub_rules, mapping_table, target_field)