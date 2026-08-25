"""
合并字段脚本 - 对 mapping entity 执行字段合并操作

CLI 用法:
    python merge_fields.py '<json_array>' '<source_fields>' '<target_field>' '<sep>'
    
示例:
    python merge_fields.py '[{"normalize":[...],"parser":{"filter":[...]}}]' 'a,b' 'd' ''
    echo '[...]' | python merge_fields.py - 'a,b' 'd' ''

import 用法:
    from merge_fields import merge_fields
    result = merge_fields(data, ["a", "b"], "d", "")
"""

import json
import sys
import copy
from typing import List


def merge_fields(
    data: list,
    source_fields: List[str],
    target_field: str,
    sep: str = "",
) -> dict:
    """
    对 mapping entity 列表执行字段合并
    
    每个 entity 的 normalize 中添加合并后的字段条目，
    parser.filter 中添加 merger 过滤器。
    
    Args:
        data: 解码后的 JSON 数组（mapping entities）
        source_fields: 源字段名列表，如 ["a", "b"]
        target_field: 目标字段名，如 "d"
        sep: 分隔符，如 "" 或 "-"
    
    Returns:
        {"status": "success"|"error", "data": [...], "message": "..."}
    """
    if not data:
        return {"status": "error", "message": "输入数据为空"}
    
    if len(source_fields) < 2:
        return {"status": "error", "message": "至少需要 2 个源字段"}
    
    results = []
    applied = 0
    skipped = 0
    for entity in data:
        entity = copy.deepcopy(entity)

        # 获取 normalize 列表
        normalize = entity.get("normalize") or []
        if not normalize:
            # 无 normalize 的 entity 无源字段可合并，如实跳过
            skipped += 1
            results.append(entity)
            continue
        
        # 构建 index → normalize item 映射
        norm_map = {item.get("index"): item for item in normalize if item.get("index")}
        
        # 验证源字段存在
        missing = [f for f in source_fields if f not in norm_map]
        if missing:
            return {
                "status": "error",
                "message": f"源字段 {missing} 不存在，可用字段: {list(norm_map.keys())}"
            }
        
        # 检查目标字段是否已存在
        if target_field in norm_map:
            return {
                "status": "error",
                "message": f"目标字段 '{target_field}' 已存在，请先删除或更换名称"
            }
        
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

    message = f"成功合并 {applied} 个 entity 的字段为 '{target_field}'"
    if skipped:
        message += f"（跳过 {skipped} 个无 normalize 的 entity）"
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
