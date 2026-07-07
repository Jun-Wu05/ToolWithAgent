"""
添加字段脚本 - 在 mapping entity 中新增字段

CLI 用法:
    python add_fields.py '<json_array>' '<field_name>' '<field_value>'
    
示例:
    python add_fields.py '[{"normalize":[...],"parser":{"filter":[...]}}]' '主机ip' '1.1.1.1'
    python add_fields.py '[...]' '请求头' '%{reqheader}'
    echo '[...]' | python add_fields.py - '主机ip' '1.1.1.1'

import 用法:
    from add_fields import add_field
    result = add_field(data, "主机ip", "1.1.1.1")
"""

import json
import sys
import copy
from typing import Optional


def add_field(
    data: list,
    field_name: str,
    field_value: Optional[str] = None,
) -> dict:
    """
    对 mapping entity 列表执行字段添加
    
    每个 entity 的 normalize 中添加新字段条目，
    parser.filter 中添加 addFields 过滤器。
    
    Args:
        data: 解码后的 JSON 数组（mapping entities）
        field_name: 新字段名，如 "主机ip"
        field_value: 字段值，如 "1.1.1.1" 或 "%{reqheader}"。
                     为 None 时表示用户未提供值。
    
    Returns:
        {"status": "success"|"error", "data": [...], "message": "..."}
    """
    if not data:
        return {"status": "error", "message": "输入数据为空"}
    
    if not field_name:
        return {"status": "error", "message": "字段名不能为空"}
    
    results = []
    for entity in data:
        entity = copy.deepcopy(entity)
        
        # 获取 normalize 列表
        normalize = entity.get("normalize", [])
        if not normalize:
            results.append(entity)
            continue
        
        # 构建 index → normalize item 映射
        norm_map = {item.get("index"): item for item in normalize if item.get("index")}
        
        # 检查字段是否已存在
        if field_name in norm_map:
            return {
                "status": "error",
                "message": f"字段 '{field_name}' 已存在，请先删除或更换名称"
            }
        
        # 处理值
        result_value = field_value if field_value is not None else ""
        
        # 1. 添加 addFields filter
        parser = entity.get("parser", {})
        filters = parser.get("filter", [])
        
        addfields_entry = {
            "name": "addFields",
            "id": "",
            "fields": {
                field_name: result_value,
            },
        }
        filters.append(addfields_entry)
        
        parser["filter"] = filters
        entity["parser"] = parser
        
        # 2. 添加 normalize 条目
        normalize_entry = {
            "mappings": [],
            "field": None,
            "sim": None,
            "result": [result_value] if result_value else [],
            "info": None,
            "entity": None,
            "required": False,
            "core": None,
            "value": None,
            "index": field_name,
        }
        normalize.append(normalize_entry)
        entity["normalize"] = normalize
        
        results.append(entity)
    
    return {"status": "success", "data": results, "message": f"成功为 {len(results)} 个 entity 添加字段 '{field_name}'"}


def main():
    """CLI 入口"""
    if len(sys.argv) < 3:
        print(json.dumps({
            "status": "error",
            "message": "用法: python add_fields.py '<json>' '<field_name>' '[<field_value>]'"
        }, ensure_ascii=False))
        sys.exit(1)
    
    try:
        data = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        if sys.argv[1] == "-":
            data = json.loads(sys.stdin.read())
        else:
            raise
    
    field_name = sys.argv[2]
    field_value = sys.argv[3] if len(sys.argv) > 3 else None
    
    result = add_field(data, field_name, field_value)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
