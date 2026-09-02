"""
映射填充共享工具 — 消除威胁填充/枚举填充/sub_rules填充中重复的 mappings 追加逻辑。

提供:
- append_mappings_to_normalize(normalize_item, mappings) → int   核心：去重追加
- apply_fill_to_sub_rules(sub_rules, mapping_table, target_field) → list  统一 sub_rules 填充
- remove_field_mappings(sub_rules, target_field) → list  取消字段映射
- unbind_fixed_fields(config, field_names) → tuple[Any, list[str]]  填充即解绑（#126）
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any


def unbind_fixed_fields(
    config: Any,
    field_names: list[str] | tuple[str, ...],
) -> tuple[Any, list[str]]:
    """删除 addFields 固定值绑定中命中目标字段的键（填充即解绑，#126）。

    固定字段（事件名称/事件级别/日志类型）由标注机制以 addFields 固定值
    写入，运行时优先于 normalize 值映射生效；用户显式枚举填充这些字段时，
    必须先解除绑定，值映射才能真正生效。normalize 条目保留（填充目标）。

    Returns:
        (更新后的配置深拷贝, 解除绑定的 entity 名单)；无命中时原样深拷贝。
    """
    targets = set(field_names)
    updated = copy.deepcopy(config)
    unbound: list[str] = []

    def _walk(node: Any) -> None:
        """递归遍历配置，移除各 entity 绑定过滤器中命中目标字段的键。"""
        if isinstance(node, dict):
            parser = node.get("parser")
            if isinstance(parser, dict) and isinstance(parser.get("filter"), list):
                touched = False
                for filter_item in parser["filter"]:
                    if (
                        isinstance(filter_item, dict)
                        and filter_item.get("name") == "addFields"
                        and filter_item.get("id") == ""
                        and isinstance(filter_item.get("fields"), dict)
                    ):
                        hit = targets & set(filter_item["fields"])
                        if hit:
                            for key in hit:
                                filter_item["fields"].pop(key)
                            touched = True
                if touched:
                    name = node.get("name")
                    unbound.append(name if isinstance(name, str) else "<未命名>")
                    # fields 清空的绑定过滤器整体移除，避免留下空 addFields
                    parser["filter"] = [
                        f for f in parser["filter"]
                        if not (
                            isinstance(f, dict)
                            and f.get("name") == "addFields"
                            and f.get("id") == ""
                            and f.get("fields") == {}
                        )
                    ]
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(updated)
    return updated, unbound


def append_mappings_to_normalize(normalize_item: dict, mappings: list[dict]) -> int:
    """向 normalize 项的 mappings 列表追加映射（按 orgValue 去重）。

    消除 enum_field_tool.py / field_mapping.py 中重复的去重追加逻辑。

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


def apply_enum_fill_with_contributions(
    config: Any,
    mapping_table: dict[str, list[dict]],
) -> tuple[Any, dict[str, list[dict[str, Any]]]]:
    """填充枚举映射，并记录每个 Sheet 实际新增规则的精确位置。"""
    updated_config = copy.deepcopy(config)
    contributions: dict[str, list[dict[str, Any]]] = {
        field_name: [] for field_name in mapping_table
    }

    def apply_to_node(node: Any, path: list[str | int]) -> None:
        """递归查找 normalize 条目，并以根配置路径记录实际新增项。"""
        if isinstance(node, dict):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for item_index, normalize_item in enumerate(normalize):
                    if not isinstance(normalize_item, dict):
                        continue
                    index_value = str(normalize_item.get("index", "")).strip()
                    field_value = str(normalize_item.get("field", "")).strip()
                    for field_name, mappings in mapping_table.items():
                        if index_value != field_name and field_value != field_name:
                            continue
                        existing_org = {
                            str(mapping.get("orgValue", ""))
                            for mapping in normalize_item.get("mappings", [])
                            if isinstance(mapping, dict)
                        }
                        for mapping in mappings:
                            org_value = str(mapping.get("orgValue", ""))
                            if org_value in existing_org:
                                continue
                            added_mapping = {
                                "mappingType": mapping.get("mappingType", "EQUAL"),
                                "orgValue": org_value,
                                "mappingValue": mapping.get("mappingValue", org_value),
                            }
                            normalize_item.setdefault("mappings", []).append(added_mapping)
                            existing_org.add(org_value)
                            contributions[field_name].append(
                                {
                                    "normalize_path": [*path, "normalize", item_index],
                                    "mapping": copy.deepcopy(added_mapping),
                                }
                            )
            for key, child in node.items():
                apply_to_node(child, [*path, key])
            return
        if isinstance(node, list):
            for item_index, child in enumerate(node):
                apply_to_node(child, [*path, item_index])

    apply_to_node(updated_config, [])
    return updated_config, contributions


def remove_enum_fill_contributions(
    config: Any,
    contributions: dict[str, list[dict[str, Any]]],
    target_fields: tuple[str, ...],
) -> Any:
    """仅撤销账本记录的枚举贡献，保留同字段的其他来源规则。"""
    updated_config = copy.deepcopy(config)
    for field_name in target_fields:
        for contribution in contributions.get(field_name, []):
            node = updated_config
            try:
                for segment in contribution.get("normalize_path", []):
                    node = node[segment]
            except (KeyError, IndexError, TypeError):
                continue
            if not isinstance(node, dict):
                continue
            mappings = node.get("mappings")
            expected = contribution.get("mapping")
            if not isinstance(mappings, list) or not isinstance(expected, dict):
                continue
            for mapping_index, mapping in enumerate(mappings):
                if mapping == expected:
                    del mappings[mapping_index]
                    break
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


def count_field_mapping_changes(
    before_config: Any,
    after_config: Any,
    target_fields: tuple[str, ...],
) -> int:
    """按映射内容统计目标字段的新增、删除和修改数量。

    同一 normalize 位置内以 ``orgValue`` 作为规则身份；内容变化算一次修改，
    仅列表顺序变化不算业务变化。重复规则使用多重集合比较，避免数量相同掩盖替换。
    """
    targets = set(target_fields)

    def collect(config: Any) -> dict[tuple[str | int, ...], dict[str, Counter[str]]]:
        """按 normalize 路径与 orgValue 收集可忽略顺序的映射内容。"""
        collected: dict[tuple[str | int, ...], dict[str, Counter[str]]] = {}

        def visit(node: Any, path: tuple[str | int, ...]) -> None:
            """递归访问配置树，只收集明确命中目标字段的 normalize 项。"""
            if isinstance(node, dict):
                normalize = node.get("normalize")
                if isinstance(normalize, list):
                    for item_index, normalize_item in enumerate(normalize):
                        if not isinstance(normalize_item, dict):
                            continue
                        index_value = str(normalize_item.get("index", "")).strip()
                        field_value = str(normalize_item.get("field", "")).strip()
                        if index_value not in targets and field_value not in targets:
                            continue
                        by_org_value: dict[str, Counter[str]] = {}
                        for mapping in normalize_item.get("mappings", []) or []:
                            if not isinstance(mapping, dict):
                                continue
                            org_value = str(mapping.get("orgValue", ""))
                            canonical = json.dumps(
                                mapping,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                                default=str,
                            )
                            by_org_value.setdefault(org_value, Counter())[canonical] += 1
                        collected[(*path, "normalize", item_index)] = by_org_value
                for key, child in node.items():
                    visit(child, (*path, key))
                return
            if isinstance(node, list):
                for item_index, child in enumerate(node):
                    visit(child, (*path, item_index))

        visit(config, ())
        return collected

    before = collect(before_config)
    after = collect(after_config)
    changed_count = 0
    for normalize_path in before.keys() | after.keys():
        before_by_org = before.get(normalize_path, {})
        after_by_org = after.get(normalize_path, {})
        for org_value in before_by_org.keys() | after_by_org.keys():
            removed = before_by_org.get(org_value, Counter()) - after_by_org.get(
                org_value, Counter()
            )
            added = after_by_org.get(org_value, Counter()) - before_by_org.get(
                org_value, Counter()
            )
            changed_count += max(sum(removed.values()), sum(added.values()))
    return changed_count


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
