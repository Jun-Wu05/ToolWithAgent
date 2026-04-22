"""
枚举字段处理工具

Agno Tool版本
"""
import json
import base64
from typing import Any, Optional

from agno.tools import tool


@tool(name="enum_field_extract", description="提取可枚举的字段")
def enum_field_tool(decoded_json: str) -> str:
    """
    提取可枚举的字段
    
    当需要识别可枚举字段时使用：
    1. 从 JSON 中提取 normalize 数组
    2. 识别可枚举的字段
    3. 返回候选字段列表
    
    Args:
        decoded_json: 解码后的 JSON 对象（字符串格式）
    
    Returns:
        可枚举字段列表
    """
    try:
        # 解析输入
        json_obj = json.loads(decoded_json) if isinstance(decoded_json, str) else decoded_json
        
        # 提取 normalize 字段
        normalize_fields = _extract_normalize_fields(json_obj)
        
        # 识别可枚举字段
        enum_candidates = _identify_enum_candidates(normalize_fields)
        
        # 生成结果
        lines = ["可枚举字段候选：", ""]
        for i, candidate in enumerate(enum_candidates[:10], 1):  # 最多显示10个
            field = candidate.get("field", "未知")
            values = candidate.get("values", [])
            count = candidate.get("count", 0)
            
            lines.append(f"{i}. **{field}**")
            lines.append(f"   - 唯一值数量: {count}")
            if values:
                lines.append(f"   - 示例: {', '.join(values[:3])}" + ("..." if len(values) > 3 else ""))
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"提取枚举字段失败: {str(e)}"


@tool(name="apply_enum_mapping", description="应用枚举映射")
def apply_enum_mapping_tool(
    json_data: str,
    mapping_table: str,
    target_field: Optional[str] = None
) -> str:
    """
    应用枚举映射到 JSON
    
    Args:
        json_data: JSON 对象（字符串格式）
        mapping_table: 映射表（JSON 字符串格式）
        target_field: 可选，指定目标字段
    
    Returns:
        应用映射后的 JSON
    """
    try:
        # 解析输入
        json_obj = json.loads(json_data) if isinstance(json_data, str) else json_data
        mappings = json.loads(mapping_table) if isinstance(mapping_table, str) else mapping_table
        
        # 按字段分组映射
        field_mappings = {}
        for item in mappings:
            field = item.get("field", "")
            if target_field and field != target_field:
                continue
            
            if field not in field_mappings:
                field_mappings[field] = {}
            
            org_value = item.get("orgValue", "")
            mapping_value = item.get("mappingValue", "")
            mapping_type = item.get("mappingType", "REGULAR")
            
            if mapping_type == "REGULAR" and org_value:
                field_mappings[field][org_value] = mapping_value
        
        # 应用映射
        result = _apply_enum_mapping(json_obj, field_mappings, target_field)
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error_message": f"应用枚举映射失败: {str(e)}"
        }, ensure_ascii=False)


def _extract_normalize_fields(json_obj: dict) -> list:
    """提取 normalize 数组中的所有字段信息"""
    fields = []
    
    def traverse(obj):
        if isinstance(obj, dict):
            if "normalize" in obj and isinstance(obj["normalize"], list):
                for item in obj["normalize"]:
                    if isinstance(item, dict):
                        field_info = {
                            "index": item.get("index", ""),
                            "field": item.get("field", ""),
                            "entity": item.get("entity", ""),
                            "result": item.get("result", []),
                        }
                        fields.append(field_info)
            
            for value in obj.values():
                traverse(value)
                
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)
    
    traverse(json_obj)
    return fields


def _identify_enum_candidates(normalize_fields: list) -> list:
    """识别可枚举的字段候选"""
    field_values = {}
    
    for item in normalize_fields:
        field = item.get("field", "")
        result = item.get("result", [])
        
        if not field:
            continue
        
        if field not in field_values:
            field_values[field] = set()
        
        if isinstance(result, list):
            for v in result:
                if v and str(v).strip():
                    field_values[field].add(str(v).strip())
        elif result:
            field_values[field].add(str(result).strip())
    
    candidates = []
    for field, values in field_values.items():
        if len(values) > 1:
            candidates.append({
                "field": field,
                "values": sorted(list(values)),
                "count": len(values)
            })
    
    # 按唯一值数量排序
    candidates.sort(key=lambda x: x["count"], reverse=True)
    return candidates


def _apply_enum_mapping(json_obj: dict, field_mappings: dict, target_field: Optional[str] = None) -> dict:
    """应用枚举映射"""
    result = json_obj.copy()
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            if "normalize" in obj and isinstance(obj["normalize"], list):
                for norm_item in obj["normalize"]:
                    if isinstance(norm_item, dict):
                        field = norm_item.get("field", "")
                        
                        if target_field and field != target_field:
                            continue
                        
                        if field in field_mappings:
                            mappings = norm_item.get("mappings", [])
                            if mappings is None:
                                mappings = []
                                norm_item["mappings"] = mappings
                            
                            existing_org_values = {m.get("orgValue", "") for m in mappings if isinstance(m, dict)}
                            
                            for org_value, mapping_value in field_mappings[field].items():
                                if org_value not in existing_org_values:
                                    mappings.append({
                                        "mappingType": "REGULAR",
                                        "orgValue": org_value,
                                        "mappingValue": mapping_value
                                    })
            
            for key, value in obj.items():
                traverse(value, f"{path}.{key}" if path else key)
                
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(result)
    return result
