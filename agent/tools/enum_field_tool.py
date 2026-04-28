"""
枚举字段处理工具

提供两套接口：
1. Agno Tool 版本 - 供 LLM Agent 调用（@tool 装饰的函数）
2. 纯函数版本 - 供外部直接调用（不依赖 Agno 框架）
"""
import json
import base64
import os
from typing import Any, Optional, List, Dict
from openpyxl import load_workbook
from collections import defaultdict

from agno.tools import tool


# ============= Agno Tool 版本（供 LLM Agent 使用）=============

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


# ============= 纯函数版本（供外部直接调用）=============

def read_enum_mappings_from_excel(excel_path: str) -> Dict[str, List[Dict]]:
    """
    从 Excel 文件读取枚举映射表
    
    Excel 格式：
    - Sheet 名 = 目标字段名
    - 第一列: mappingType (EQUAL 或 REGULAR)
    - 第二列: orgValue (原始值)
    - 第三列: mappingValue (映射值)
    
    Args:
        excel_path: Excel 文件路径
    
    Returns:
        Dict[str, List[Dict]], key 是 Sheet 名，value 是映射列表
        格式: {"threat_type": [{"mappingType": "REGULAR", "orgValue": "sql注入", "mappingValue": "SQL注入"}], ...}
    """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel 文件不存在: {excel_path}")
    
    all_mappings = defaultdict(list)
    valid_types = {"EQUAL", "REGULAR"}
    
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_mappings = []
            
            for row in ws.iter_rows(min_row=2, max_col=3, values_only=True):
                # 跳过空行
                if row[1] is None:
                    continue
                
                # 读取映射类型，默认 EQUAL
                mapping_type = str(row[0]).upper() if row[0] else "EQUAL"
                if mapping_type not in valid_types:
                    mapping_type = "EQUAL"
                
                org_value = str(row[1]).strip() if row[1] else ""
                mapping_value = str(row[2]).strip() if row[2] else ""
                
                if not org_value:
                    continue
                
                # 对于 REGULAR 类型，添加通配符
                if mapping_type == "REGULAR":
                    if not org_value.startswith(".*"):
                        org_value = ".*" + org_value
                    if not org_value.endswith(".*"):
                        org_value = org_value + ".*"
                
                sheet_mappings.append({
                    "mappingType": mapping_type,
                    "orgValue": org_value,
                    "mappingValue": mapping_value or org_value
                })
            
            if sheet_mappings:
                all_mappings[sheet_name] = sheet_mappings
    finally:
        wb.close()
    
    return dict(all_mappings)


def get_enum_preview(excel_path: str) -> List[Dict]:
    """
    获取枚举映射预览数据，用于 DataFrame 展示
    
    将多 Sheet 的映射表展平为列表，每个元素包含字段名和映射信息
    
    Args:
        excel_path: Excel 文件路径
    
    Returns:
        List[Dict], 展平后的映射列表
        格式: [{"目标字段": "threat_type", "mappingType": "REGULAR", "orgValue": "sql注入", "mappingValue": "SQL注入"}, ...]
    """
    mappings = read_enum_mappings_from_excel(excel_path)
    
    preview = []
    for field_name, field_mappings in mappings.items():
        for mapping in field_mappings:
            # 去掉通配符显示
            display_org = mapping["orgValue"]
            if display_org.startswith(".*") and display_org.endswith(".*"):
                display_org = display_org[2:-2]
            
            preview.append({
                "目标字段": field_name,
                "mappingType": mapping["mappingType"],
                "原始值": display_org,
                "映射值": mapping["mappingValue"]
            })
    
    return preview


def apply_enum_fill(
    decoded_data: Any,
    excel_path: str,
    target_fields: Optional[List[str]] = None
) -> Any:
    """
    应用枚举填充
    
    遍历 normalize 数组，根据 Excel 映射表对目标字段添加 mappings
    
    Args:
        decoded_data: 解码后的 JSON 对象（或 Base64 字符串，会自动解码）
        excel_path: Excel 映射表文件路径
        target_fields: 可选，指定目标字段列表；None 表示全部 Sheet 字段
    
    Returns:
        更新后的 JSON 对象
    
    Raises:
        FileNotFoundError: Excel 文件不存在
        ValueError: decoded_data 解析失败
    """
    # 如果是 Base64 字符串，先解码
    if isinstance(decoded_data, str):
        try:
            decoded_data = base64.b64decode(decoded_data.encode('ascii'))
            decoded_data = json.loads(decoded_data.decode('utf-8'))
        except Exception as e:
            raise ValueError(f"Base64 解码失败: {str(e)}")
    
    # 读取映射表
    all_mappings = read_enum_mappings_from_excel(excel_path)
    
    # 如果指定了目标字段，只使用这些字段的映射
    if target_fields:
        filtered_mappings = {}
        for field in target_fields:
            if field in all_mappings:
                filtered_mappings[field] = all_mappings[field]
        all_mappings = filtered_mappings
    
    # 深拷贝避免修改原数据
    result = json.loads(json.dumps(decoded_data))
    
    # 处理可能是列表的情况
    if isinstance(result, list):
        data_list = result
    else:
        data_list = [result]
    
    # 遍历每个数据项
    for data_item in data_list:
        if not isinstance(data_item, dict):
            continue
        
        normalize = data_item.get("normalize", [])
        if not normalize:
            continue
        
        # 遍历映射表
        for field_name, field_mappings in all_mappings.items():
            # 查找匹配的 normalize 项
            for norm_item in normalize:
                if not isinstance(norm_item, dict):
                    continue
                
                # 匹配字段：index 或 field
                index_value = str(norm_item.get("index", "")).strip()
                field_value = str(norm_item.get("field", "")).strip()
                
                matched = (
                    index_value == field_name
                    or field_value == field_name
                    or field_name in index_value
                    or field_name in field_value
                )
                
                if not matched:
                    continue
                
                # 获取或初始化 mappings
                mappings = norm_item.get("mappings")
                if mappings is None:
                    mappings = []
                    norm_item["mappings"] = mappings
                
                # 已存在的 orgValue 集合
                existing_org = {m.get("orgValue", "") for m in mappings if isinstance(m, dict)}
                
                # 添加新映射
                for mapping in field_mappings:
                    org_value = mapping.get("orgValue", "")
                    if org_value not in existing_org:
                        mappings.append({
                            "mappingType": mapping.get("mappingType", "REGULAR"),
                            "orgValue": org_value,
                            "mappingValue": mapping.get("mappingValue", org_value)
                        })
    
    return result


def export_enum_to_base64(data: Any) -> str:
    """
    将 JSON 对象导出为 Base64 编码字符串
    
    Args:
        data: JSON 对象（字典或列表）
    
    Returns:
        str, Base64 编码字符串
    """
    json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    base64_bytes = base64.b64encode(json_str.encode('utf-8'))
    return base64_bytes.decode('utf-8')


def apply_enum_with_base64(
    base64_data: str,
    excel_path: str,
    target_fields: Optional[List[str]] = None
) -> str:
    """
    一站式枚举填充函数：解码 -> 填充 -> 编码
    
    Args:
        base64_data: Base64 编码的 JSON 字符串
        excel_path: Excel 映射表文件路径
        target_fields: 可选，指定目标字段列表
    
    Returns:
        str, 填充后的 Base64 编码字符串
    """
    # 1. 解码
    decoded = base64.b64decode(base64_data.encode('ascii'))
    data = json.loads(decoded.decode('utf-8'))
    
    # 2. 应用填充
    result = apply_enum_fill(data, excel_path, target_fields)
    
    # 3. 编码
    return export_enum_to_base64(result)


# ============= 内部辅助函数 =============

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
