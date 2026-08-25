"""
删除字段脚本 - 从 mapping entity 中移除字段

CLI 用法:
    python delete_fields.py '<json_array>' '<fields_to_delete>'
    
示例:
    python delete_fields.py '[{"normalize":[...],"parser":{"filter":[...]}}]' 'a'
    python delete_fields.py '[...]' 'a,b'
    echo '[...]' | python delete_fields.py - 'a,b'

import 用法:
    from delete_fields import delete_field
    result = delete_field(data, ["a"])
    result = delete_field(data, ["a", "b"])
"""

import json
import sys
import copy
from typing import List


# 系统保留字段，不允许删除：
# - original_log / rule_name_list：脚本原有保留字段
# - 日志类型：子规则分流依赖的核心字段，删除会破坏规则结构
RESERVED_FIELDS = {"original_log", "rule_name_list", "日志类型"}


def delete_field(
    data: list,
    fields_to_delete: List[str],
) -> dict:
    """
    对 mapping entity 列表执行字段删除
    
    每个 entity 的 normalize 中移除匹配的条目，
    parser.filter 中添加 removeFields 过滤器。
    
    Args:
        data: 解码后的 JSON 数组（mapping entities）
        fields_to_delete: 要删除的字段名列表，如 ["a"] 或 ["a", "b"]
    
    Returns:
        {"status": "success"|"error", "data": [...], "message": "..."}
    """
    if not data:
        return {"status": "error", "message": "输入数据为空"}
    
    if not fields_to_delete:
        return {"status": "error", "message": "未指定要删除的字段"}
    
    results = []
    applied = 0
    skipped = 0
    for entity in data:
        entity = copy.deepcopy(entity)

        # 获取 normalize 列表
        normalize = entity.get("normalize") or []
        if not normalize:
            # 无 normalize 的 entity 无字段可删，如实跳过
            skipped += 1
            results.append(entity)
            continue
        
        # 构建 index → normalize item 映射
        norm_map = {item.get("index"): item for item in normalize if item.get("index")}
        
        # 验证要删除的字段存在（排除保留字段）
        missing = [f for f in fields_to_delete if f not in norm_map]
        reserved = [f for f in fields_to_delete if f in RESERVED_FIELDS]
        
        if reserved:
            return {
                "status": "error",
                "message": f"字段 {reserved} 为系统保留字段，不允许删除"
            }
        
        # 1. 添加 removeFields filter
        parser = entity.get("parser") or {}
        # 入口规则模板的 filter 可能为 null，初始化为空数组再追加
        filters = parser.get("filter") or []
        
        # 检查是否已存在 removeFields filter，有则合并
        existing_remove = None
        for i, f in enumerate(filters):
            if f.get("name") == "removeFields":
                existing_remove = i
                break
        
        if existing_remove is not None:
            # 合并到已有的 removeFields 中
            existing_fields = filters[existing_remove].get("fields", [])
            for fld in fields_to_delete:
                if fld not in existing_fields:
                    existing_fields.append(fld)
            filters[existing_remove]["fields"] = existing_fields
        else:
            remove_entry = {
                "name": "removeFields",
                "id": "",
                "fields": [f for f in fields_to_delete if f in norm_map],
            }
            filters.append(remove_entry)
        
        parser["filter"] = filters
        entity["parser"] = parser
        
        # 2. 移除 normalize 条目（仅移除存在的字段）
        deletable = [f for f in fields_to_delete if f in norm_map]
        entity["normalize"] = [
            item for item in normalize
            if item.get("index") not in deletable
        ]

        applied += 1
        results.append(entity)

    deleted_count = len([f for f in fields_to_delete if f not in missing])
    message = f"成功从 {applied} 个 entity 删除 {deleted_count} 个字段"
    if skipped:
        message += f"（跳过 {skipped} 个无 normalize 的 entity）"
    return {
        "status": "success",
        "data": results,
        "message": message,
        "not_found": missing if missing else None,
    }


def main():
    """CLI 入口"""
    if len(sys.argv) < 3:
        print(json.dumps({
            "status": "error",
            "message": "用法: python delete_fields.py '<json>' '<fields_to_delete>'"
        }, ensure_ascii=False))
        sys.exit(1)
    
    try:
        data = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        if sys.argv[1] == "-":
            data = json.loads(sys.stdin.read())
        else:
            raise
    
    fields_to_delete = sys.argv[2].split(",")
    
    result = delete_field(data, fields_to_delete)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
