"""
映射填充共享工具 — 消除威胁填充/枚举填充/sub_rules填充中重复的 mappings 追加逻辑。

提供:
- append_mappings_to_normalize(normalize_item, mappings) → int   核心：去重追加
- apply_fill_to_sub_rules(sub_rules, mapping_table, target_field) → list  统一 sub_rules 填充
- remove_field_mappings(sub_rules, target_field) → list  取消字段映射
"""
from __future__ import annotations

import copy
from typing import Any


def append_mappings_to_normalize(normalize_item: dict, mappings: list[dict]) -> int:
    """向 normalize 项的 mappings 列表追加映射（按 orgValue 去重）。

    消除 threat_fill.py / enum_field_tool.py / field_mapping.py 中4处重复的去重追加逻辑。

    Args:
        normalize_item: normalize 条目（会被原地修改）
        mappings: 待追加的映射列表 [{mappingType, orgValue, mappingValue}, ...]

    Returns:
        实际新增的映射数量
    """
    existing_org = {m.get("orgValue", "") for m in normalize_item.get("mappings", []) if isinstance(m, dict)}
    added = 0
    for mapping in mappings:
        org_value = mapping.get("orgValue", "")
        if org_value not in existing_org:
            normalize_item.setdefault("mappings", []).append({
                "mappingType": mapping.get("mappingType", "EQUAL"),
                "orgValue": org_value,
                "mappingValue": mapping.get("mappingValue", org_value),
            })
            existing_org.add(org_value)
            added += 1
    return added


def apply_fill_to_sub_rules(
    sub_rules: list[dict],
    mapping_table: dict[str, list[dict]] | list[dict],
    target_field: str | None = None,
) -> list[dict]:
    """对子规则列表统一应用映射填充（mappings 追加）。

    合并 apply_enum_fill_to_sub_rules 和威胁填充的 sub_rules 逻辑。
    威胁填充和枚举填充在 apply 层面是同一操作（找 normalize 项 → 追加 mappings），
    区别只是 mappingType（REGULAR vs EQUAL），由 mapping_table 内容决定。

    Args:
        sub_rules: 子规则列表（会被深拷贝，不修改原数据）
        mapping_table: 映射表。支持两种格式：
            - dict: {字段名: [{mappingType, orgValue, mappingValue}, ...]}（枚举填充，Excel 多 sheet）
            - list: [{mappingType, orgValue, mappingValue}, ...]（威胁填充，单字段，需配 target_field）
        target_field: 目标字段名。mapping_table 为 list 时必填；为 dict 时可选（None=填充表里所有字段）

    Returns:
        深拷贝后的 sub_rules，匹配的 normalize 项已追加 mappings
    """
    # 统一 mapping_table 为 dict 格式
    if isinstance(mapping_table, list):
        if not target_field:
            return copy.deepcopy(sub_rules)
        field_mappings_dict = {target_field: mapping_table}
    else:
        if target_field:
            field_mappings_dict = {target_field: mapping_table.get(target_field, [])}
        else:
            field_mappings_dict = mapping_table

    if not field_mappings_dict:
        return copy.deepcopy(sub_rules)

    result_rules = copy.deepcopy(sub_rules)

    for rule in result_rules:
        for norm_item in rule.get("normalize", []):
            if not isinstance(norm_item, dict):
                continue
            index_value = str(norm_item.get("index", "")).strip()
            field_value = str(norm_item.get("field", "")).strip()

            for field_name, mappings in field_mappings_dict.items():
                if not mappings:
                    continue
                matched = index_value == field_name or field_value == field_name
                if matched:
                    append_mappings_to_normalize(norm_item, mappings)

    return result_rules


def remove_field_mappings(sub_rules: list[dict], target_field: str) -> list[dict]:
    """取消指定字段的映射（清空其 mappings）。

    支持「取消alarm_category的映射」等自然语言指令。

    Args:
        sub_rules: 子规则列表（会被深拷贝）
        target_field: 要清除映射的字段名

    Returns:
        深拷贝后的 sub_rules，匹配的 normalize 项 mappings 已清空
    """
    result_rules = copy.deepcopy(sub_rules)

    for rule in result_rules:
        for norm_item in rule.get("normalize", []):
            if not isinstance(norm_item, dict):
                continue
            index_value = str(norm_item.get("index", "")).strip()
            field_value = str(norm_item.get("field", "")).strip()
            if index_value == target_field or field_value == target_field:
                norm_item["mappings"] = []

    return result_rules
