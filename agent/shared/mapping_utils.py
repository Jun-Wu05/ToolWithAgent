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


def apply_fill_to_config(
    config: Any,
    mapping_table: dict[str, list[dict]] | list[dict],
    target_field: str | None = None,
) -> Any:
    """在保持完整根结构的前提下递归填充所有 normalize 条目。

    参数：
        config: 解码后的完整配置或子规则列表。
        mapping_table: 按字段分组的枚举映射，或单字段映射列表。
        target_field: 当映射来源是列表时必须提供的目标字段。

    返回值：
        深拷贝后的完整配置；输入对象不会被修改。

    不变量：
        只修改目标 normalize 条目的 mappings，其他配置结构必须原样保留。
    """
    # 统一为按字段分组的结构，遍历阶段不再猜测映射来源类型。
    if isinstance(mapping_table, list):
        if not target_field:
            return copy.deepcopy(config)
        field_mappings = {target_field: mapping_table}
    elif target_field:
        field_mappings = {target_field: mapping_table.get(target_field, [])}
    else:
        field_mappings = mapping_table

    updated_config = copy.deepcopy(config)
    if not field_mappings:
        return updated_config

    def apply_to_node(node: Any) -> None:
        """递归访问容器，并只在明确的 normalize 列表内追加映射。"""
        if isinstance(node, dict):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for normalize_item in normalize:
                    if not isinstance(normalize_item, dict):
                        continue
                    index_value = str(normalize_item.get("index", "")).strip()
                    field_value = str(normalize_item.get("field", "")).strip()
                    for field_name, mappings in field_mappings.items():
                        if mappings and (index_value == field_name or field_value == field_name):
                            append_mappings_to_normalize(normalize_item, mappings)
            for child in node.values():
                apply_to_node(child)
            return
        if isinstance(node, list):
            for child in node:
                apply_to_node(child)

    apply_to_node(updated_config)
    return updated_config


def count_field_mappings(config: Any, target_fields: tuple[str, ...]) -> int:
    """递归统计目标字段 mappings 数量，供执行前后变更验证使用。"""
    targets = set(target_fields)
    count = 0

    def count_node(node: Any) -> None:
        """访问配置树并累计明确命中目标字段的 mappings。"""
        nonlocal count
        if isinstance(node, dict):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for normalize_item in normalize:
                    if not isinstance(normalize_item, dict):
                        continue
                    index_value = str(normalize_item.get("index", "")).strip()
                    field_value = str(normalize_item.get("field", "")).strip()
                    if index_value in targets or field_value in targets:
                        count += len(normalize_item.get("mappings", []) or [])
            for child in node.values():
                count_node(child)
            return
        if isinstance(node, list):
            for child in node:
                count_node(child)

    count_node(config)
    return count


def remove_field_mappings_from_config(config: Any, target_field: str) -> Any:
    """在保持完整根结构的前提下递归清空目标字段 mappings。"""
    updated_config = copy.deepcopy(config)

    def remove_from_node(node: Any) -> None:
        """访问配置树并清空明确命中的 normalize 映射。"""
        if isinstance(node, dict):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for normalize_item in normalize:
                    if not isinstance(normalize_item, dict):
                        continue
                    index_value = str(normalize_item.get("index", "")).strip()
                    field_value = str(normalize_item.get("field", "")).strip()
                    if index_value == target_field or field_value == target_field:
                        normalize_item["mappings"] = []
            for child in node.values():
                remove_from_node(child)
            return
        if isinstance(node, list):
            for child in node:
                remove_from_node(child)

    remove_from_node(updated_config)
    return updated_config

def apply_fill_to_sub_rules(
    sub_rules: list[dict],
    mapping_table: dict[str, list[dict]] | list[dict],
    target_field: str | None = None,
) -> list[dict]:
    """兼容子规则调用，并委托保持根结构的通用配置填充实现。"""
    return apply_fill_to_config(sub_rules, mapping_table, target_field)

def remove_field_mappings(sub_rules: list[dict], target_field: str) -> list[dict]:
    """兼容子规则调用，并委托保持根结构的通用取消映射实现。"""
    return remove_field_mappings_from_config(sub_rules, target_field)
