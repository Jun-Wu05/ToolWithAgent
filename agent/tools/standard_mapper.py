"""
标准字段映射工具

Agno Tool版本
"""
import json
import base64
import os
from typing import Any, Optional

from agno.tools import tool
from openpyxl import load_workbook


@tool(name="field_mapping", description="执行标准字段映射")
def field_mapping_tool(
    decoded_json: str,
    field_mapping_table: str,
    excel_template_path: Optional[str] = None
) -> str:
    """
    执行标准字段映射
    
    当需要将原始字段映射到标准字段时使用：
    1. 接收解码后的 JSON 和映射表
    2. 应用字段映射
    3. 管理 simEntities 数组
    4. 返回映射后的 JSON
    
    Args:
        decoded_json: 解码后的 JSON 对象（字符串格式）
        field_mapping_table: 字段映射表（JSON 字符串格式）
            [
                {"原始字段名": "content.srcip", "系统属性名称": "源地址", "匹配状态": "匹配成功"},
                ...
            ]
        excel_template_path: 可选，Excel 模板路径
    
    Returns:
        映射结果
    """
    try:
        # 解析输入
        json_obj = json.loads(decoded_json) if isinstance(decoded_json, str) else decoded_json
        mapping_table = json.loads(field_mapping_table) if isinstance(field_mapping_table, str) else field_mapping_table
        
        # 默认 Excel 模板路径
        if excel_template_path is None:
            excel_template_path = os.path.join(
                os.getcwd(), "config", "对象.xlsx"
            )
        
        # 读取 Excel 模板
        object_mapping = {}
        if os.path.exists(excel_template_path):
            object_mapping = _load_object_mapping(excel_template_path)
        
        # 解析字段映射表
        field_to_object = {}
        field_to_new_value = {}
        
        for mapping in mapping_table:
            original_field = mapping.get("原始字段名", "")
            system_property = mapping.get("系统属性名称", "")
            match_status = mapping.get("匹配状态", "")
            
            if "匹配成功" in match_status:
                obj = object_mapping.get(system_property, "事件")
                field_to_object[original_field] = obj
                field_to_new_value[original_field] = system_property
        
        # 应用映射
        processed_json = _apply_field_mapping(json_obj, field_to_new_value, field_to_object)
        
        # 管理 simEntities
        entities_added = _manage_sim_entities(processed_json, field_to_object)
        
        result = {
            "status": "success",
            "processed_json": processed_json,
            "fields_mapped": len(field_to_new_value),
            "entities_added": list(set(entities_added)),
            "message": f"成功映射 {len(field_to_new_value)} 个字段"
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error_message": f"标准字段映射失败: {str(e)}"
        }, ensure_ascii=False)


@tool(name="generate_mapping_table", description="生成字段映射表")
def generate_mapping_table_tool(
    decoded_json: str,
    fields: str
) -> str:
    """
    生成字段映射表
    
    根据解码后的 JSON 和提取的字段，生成建议的映射表：
    1. 接收 JSON 和字段列表
    2. 分析每个字段的可能含义
    3. 生成映射建议
    4. 返回 Markdown 格式的映射表
    
    Args:
        decoded_json: 解码后的 JSON 对象（字符串格式）
        fields: 提取的字段列表（JSON 数组字符串）
    
    Returns:
        Markdown 格式的映射表
    """
    try:
        # 解析输入
        json_obj = json.loads(decoded_json) if isinstance(decoded_json, str) else decoded_json
        field_list = json.loads(fields) if isinstance(fields, str) else fields
        
        # 生成映射表
        mapping_lines = [
            "| 原始字段 | 建议标准字段 | 匹配状态 | 匹配理由 |",
            "|----------|-------------|---------|---------|"
        ]
        
        # 常见字段映射规则
        field_rules = {
            "srcip": ("源地址", "IP地址字段"),
            "dstip": ("目的地址", "IP地址字段"),
            "srcport": ("源端口", "端口字段"),
            "dstport": ("目的端口", "端口字段"),
            "protocol": ("协议", "协议字段"),
            "threat_type": ("威胁类型", "安全相关字段"),
            "action": ("动作", "处理动作字段"),
            "time": ("时间", "时间字段"),
            "content": ("内容", "内容字段"),
        }
        
        for field in field_list:
            field_str = str(field).strip()
            
            # 尝试匹配规则
            matched = False
            for pattern, (std_field, reason) in field_rules.items():
                if pattern in field_str.lower():
                    mapping_lines.append(f"| {field_str} | {std_field} | 匹配成功 | {reason} |")
                    matched = True
                    break
            
            if not matched:
                mapping_lines.append(f"| {field_str} | 需确认 | 待匹配 | 需要根据上下文判断 |")
        
        return "\n".join(mapping_lines)
        
    except Exception as e:
        return f"生成映射表失败: {str(e)}"


def _load_object_mapping(excel_path: str) -> dict:
    """读取 Excel 模板的"对应关系" Sheet"""
    mapping = {}
    try:
        wb = load_workbook(excel_path, data_only=True)
        if "对应关系" in wb.sheetnames:
            ws = wb["对应关系"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if len(row) >= 3 and row[0] and row[2]:
                    system_property = str(row[0]).strip()
                    obj = str(row[2]).strip()
                    mapping[system_property] = obj
    except Exception:
        pass
    return mapping


def _apply_field_mapping(json_obj: dict, field_mapping: dict, field_to_object: dict = None) -> dict:
    """应用字段映射到 JSON 对象"""
    result = json_obj.copy()
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            if "normalize" in obj and isinstance(obj["normalize"], list):
                for item in obj["normalize"]:
                    if isinstance(item, dict):
                        original_index = str(item.get("index", "") or "").strip().lower()
                        result_values = item.get("result", [])
                        if isinstance(result_values, list):
                            result_values_lower = [str(v).strip().lower() for v in result_values if v is not None]
                        else:
                            result_values_lower = [str(result_values).strip().lower()]
                        
                        matched = False
                        for original_field, mapped_field in field_mapping.items():
                            original_lower = str(original_field).strip().lower()
                            
                            if (original_lower == original_index or 
                                original_lower in original_index or
                                original_lower in result_values_lower):
                                
                                final_field = mapped_field
                                entity = "事件"
                                
                                if field_to_object and final_field in field_to_object:
                                    entity = field_to_object[final_field]
                                
                                item["field"] = final_field
                                item["entity"] = entity
                                item["core"] = False
                                item["sim"] = True
                                matched = True
                                break
                        
                        if not matched and original_index in field_mapping:
                            mapped_field = field_mapping[original_index]
                            final_field = mapped_field
                            entity = "事件"
                            
                            if field_to_object and final_field in field_to_object:
                                entity = field_to_object[final_field]
                            
                            item["field"] = final_field
                            item["entity"] = entity
                            item["core"] = False
                            item["sim"] = True
            
            for key, value in obj.items():
                if key != "normalize":
                    traverse(value, f"{path}.{key}" if path else key)
                    
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(result)
    return result


def _manage_sim_entities(json_obj: dict, field_to_object: dict) -> list:
    """管理 simEntities 数组"""
    entities_added = []
    objects_needed = set(field_to_object.values())
    
    def find_or_create_sim_entities(obj):
        nonlocal entities_added
        
        if isinstance(obj, dict):
            if "simEntities" in obj and isinstance(obj["simEntities"], list):
                sim_entities = obj["simEntities"]
                existing_objects = {e.get("object") for e in sim_entities if isinstance(e, dict)}
                
                for obj_type in objects_needed:
                    if obj_type not in existing_objects:
                        new_entity = {
                            "object": obj_type,
                            "fields": []
                        }
                        sim_entities.append(new_entity)
                        entities_added.append(obj_type)
            
            for value in obj.values():
                find_or_create_sim_entities(value)
                
        elif isinstance(obj, list):
            for item in obj:
                find_or_create_sim_entities(item)
    
    find_or_create_sim_entities(json_obj)
    return entities_added
