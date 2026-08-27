r"""
合并字段脚本 - 对 mapping entity 执行字段合并操作（per-entity 自适应，#147）

CLI 用法:
    python merge_fields.py '<json_array>' '<source_fields>' '<target_field>' '<sep>'

import 用法:
    from merge_fields import merge_fields
    result = merge_fields(data, ["a", "b"], "d", "")
"""

import json
import sys
import copy
from typing import List, Optional


def merge_fields(
    data: list,
    source_fields: List[str],
    target_field: str,
    sep: str = "",
    target_names: Optional[List[str]] = None,
) -> dict:
    """
    对 mapping entity 列表执行字段合并（per-entity 自适应，#147）。

    子规则字段集互不相同（映射表展示的是并集）：源字段齐全的 entity
    执行合并；缺任一源或目标已存在的 entity **跳过并按子规则名报告**；
    所有目标 entity 都缺源时才返回 field_not_found。

    Args:
        data: 解码后的 JSON 数组（mapping entities）
        source_fields: 源字段名列表，如 ["a", "b"]
        target_field: 目标字段名，如 "d"
        sep: 分隔符，如 "" 或 "-"
        target_names: 目标 entity 名单（按 name 精确匹配，#126）；
                      None 表示全部 entity。名单外的 entity 原样透传。

    Returns:
        {"status": "success"|"error", "data": [...], "message": "..."}
    """
    if not data:
        return {"status": "error", "message": "输入数据为空"}

    if len(source_fields) < 2:
        return {"status": "error", "message": "至少需要 2 个源字段"}

    targets = set(target_names) if target_names else None
    results = []
    applied = 0
    skipped_empty = 0
    skipped_reasons: list[tuple[str, str]] = []
    all_missing_source = True
    union_indexes: set[str] = set()

    for entity in data:
        entity = copy.deepcopy(entity)

        if targets is not None and entity.get("name") not in targets:
            results.append(entity)
            continue

        # 获取 normalize 列表
        normalize = entity.get("normalize") or []
        name = entity.get("name") or "<未命名>"
        if not normalize:
            # 无 normalize 的 entity 无源字段可合并，如实跳过
            skipped_empty += 1
            results.append(entity)
            continue

        # 构建 index → normalize item 映射
        norm_map = {item.get("index"): item for item in normalize if item.get("index")}
        union_indexes.update(norm_map)

        missing = [f for f in source_fields if f not in norm_map]
        if missing:
            skipped_reasons.append((name, f"缺 {'、'.join(missing)}"))
            results.append(entity)
            continue
        all_missing_source = False

        # 检查目标字段是否已存在（该 entity 跳过而非整体失败，#147）
        if target_field in norm_map:
            skipped_reasons.append((name, f"目标 '{target_field}' 已存在"))
            results.append(entity)
            continue

        # 计算合并后的 result 值
        merged_result = sep.join(
            norm_map[f].get("result", [""])[0] if norm_map[f].get("result") else ""
            for f in source_fields
        )

        # 1. 添加 merger filter
        parser = entity.get("parser") or {}
        # 入口规则模板的 filter 可能为 null，初始化为空数组再追加
        filters = parser.get("filter") or []

        # 检查是否已存在相同目标字段的 merger，有则更新
        existing_idx = None
        for i, f in enumerate(filters):
            if f.get("name") == "merger" and f.get("field") == target_field:
                existing_idx = i
                break

        merger_entry = {
            "name": "merger",
            "field": target_field,
            "sep": sep,
            "id": "",
            "fields": source_fields,
        }

        if existing_idx is not None:
            filters[existing_idx] = merger_entry
        else:
            filters.append(merger_entry)

        parser["filter"] = filters
        entity["parser"] = parser

        # 2. 添加 normalize 条目
        normalize_entry = {
            "mappings": [],
            "field": None,
            "sim": None,
            "result": [merged_result],
            "info": None,
            "entity": None,
            "required": False,
            "core": None,
            "value": None,
            "index": target_field,
        }
        normalize.append(normalize_entry)
        entity["normalize"] = normalize

        applied += 1
        results.append(entity)

    # 所有目标 entity 都缺源字段 → 真正的 field_not_found（并集词表辅助定位）
    if applied == 0 and skipped_reasons and all_missing_source:
        preview = "、".join(sorted(union_indexes)[:30])
        return {
            "status": "error",
            "message": (
                f"源字段 {source_fields} 不存在于任何（目标）子规则；"
                f"全部子规则字段并集：{preview}"
                + ("等" if len(union_indexes) > 30 else "")
            ),
        }

    message = f"成功合并 {applied} 个 entity 的字段为 '{target_field}'"
    if targets is not None:
        message += f"（目标 {len(targets)} 个）"
    if skipped_reasons:
        detail = "；".join(f"{n}（{r}）" for n, r in skipped_reasons[:5])
        more = f" 等 {len(skipped_reasons)} 条" if len(skipped_reasons) > 5 else ""
        message += f"；跳过：{detail}{more}"
    if skipped_empty:
        message += f"（跳过 {skipped_empty} 个无 normalize 的 entity）"
    return {"status": "success", "data": results, "message": message}


def main():
    """CLI 入口"""
    if len(sys.argv) < 5:
        print(json.dumps({
            "status": "error",
            "message": "用法: python merge_fields.py '<json>' '<source_fields>' '<target_field>' '<sep>"
        }, ensure_ascii=False))
        sys.exit(1)

    try:
        data = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        if sys.argv[1] == "-":
            data = json.loads(sys.stdin.read())
        else:
            raise

    source_fields = sys.argv[2].split(",")
    target_field = sys.argv[3]
    sep = sys.argv[4]

    result = merge_fields(data, source_fields, target_field, sep)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
