"""
威胁类型处理工具

Agno Tool版本
"""
import json
import os
from typing import Any, Optional

from agno.tools import tool


# 默认威胁类型列表
DEFAULT_THREAT_TYPES = [
    "SQL注入攻击",
    "XSS攻击",
    "跨站请求伪造",
    "命令注入攻击",
    "webshell",
    "暴力破解攻击",
    "网络钓鱼攻击",
    "权限绕过攻击",
    "敏感信息泄露",
    "远程代码执行",
    "文件包含攻击",
    "其他"
]


@tool(name="threat_type_mapping", description="生成威胁类型映射表")
def threat_type_tool(decoded_json: str) -> str:
    """
    生成威胁类型映射表
    
    当需要标准化威胁类型时使用：
    1. 从 JSON 中提取威胁类型值
    2. 匹配到标准威胁类型
    3. 生成映射表
    4. 返回 Markdown 格式的映射建议
    
    Args:
        decoded_json: 解码后的 JSON 对象（字符串格式）
    
    Returns:
        Markdown 格式的威胁类型映射表
    """
    try:
        # 解析输入
        json_obj = json.loads(decoded_json) if isinstance(decoded_json, str) else decoded_json
        
        # 提取威胁类型值
        threat_values = _extract_threat_values(json_obj)
        
        # 加载配置的威胁类型
        all_threat_types = _load_threat_types()
        
        # 生成映射表
        mapping_lines = [
            "| 原始威胁值 | 建议映射 | 匹配状态 |",
            "|------------|---------|---------|"
        ]
        
        for threat_value in threat_values:
            matched_type = _find_matching_threat_type(threat_value, all_threat_types)
            status = "自动匹配" if matched_type != "其他" else "需确认"
            mapping_lines.append(f"| {threat_value} | {matched_type} | {status} |")
        
        result = {
            "threat_values": threat_values,
            "all_threat_types": all_threat_types,
            "mapping_table": "\n".join(mapping_lines)
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error_message": f"威胁类型映射失败: {str(e)}"
        }, ensure_ascii=False)


@tool(name="apply_threat_mapping", description="应用威胁类型映射到JSON")
def apply_threat_mapping_tool(
    json_data: str,
    mapping_table: str
) -> str:
    """
    应用威胁类型映射到 JSON 对象
    
    Args:
        json_data: JSON 对象（字符串格式）
        mapping_table: 映射表（JSON 字符串格式）
            [
                {"orgValue": "SQL注入", "mappingValue": "SQL注入攻击"},
                ...
            ]
    
    Returns:
        应用映射后的 JSON
    """
    try:
        # 解析输入
        json_obj = json.loads(json_data) if isinstance(json_data, str) else json_data
        mappings = json.loads(mapping_table) if isinstance(mapping_table, str) else mapping_table
        
        # 构建映射字典
        mapping_dict = {}
        for item in mappings:
            org_value = item.get("orgValue", "")
            mapping_value = item.get("mappingValue", "")
            if org_value and mapping_value:
                mapping_dict[org_value] = mapping_value
        
        # 应用映射
        result = _apply_threat_mapping(json_obj, mapping_dict)
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error_message": f"应用威胁映射失败: {str(e)}"
        }, ensure_ascii=False)


def _load_threat_types() -> list:
    """从配置文件加载威胁类型"""
    config_path = os.path.join(os.getcwd(), "config", "threat_type_config.json")
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                threat_types = config.get('threat_types', [])
                return [tt.get('name') for tt in threat_types if tt.get('name')]
        except Exception:
            pass
    
    return DEFAULT_THREAT_TYPES


def _extract_threat_values(json_obj: dict) -> list:
    """从 JSON 中提取威胁类型值"""
    threat_values = []
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            threat_field_names = ['threatType', 'threat_type', 'alertType', 'attackType', 'threat', 'category']
            
            for field_name in threat_field_names:
                if field_name in obj and obj[field_name]:
                    value = obj[field_name]
                    if isinstance(value, str) and value.strip():
                        if value not in threat_values:
                            threat_values.append(value)
            
            for key, value in obj.items():
                traverse(value, f"{path}.{key}" if path else key)
                
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(json_obj)
    return threat_values


def _find_matching_threat_type(value: str, threat_types: list) -> str:
    """匹配威胁类型"""
    value_lower = value.lower()
    
    for threat_type in threat_types:
        if threat_type.lower() in value_lower or value_lower in threat_type.lower():
            return threat_type
    
    # 关键词匹配
    keywords_map = {
        "sql": "SQL注入攻击",
        "xss": "XSS攻击",
        "csrf": "跨站请求伪造",
        "命令": "命令注入攻击",
        "shell": "webshell",
        "暴力": "暴力破解攻击",
        "钓鱼": "网络钓鱼攻击",
        "绕过": "权限绕过攻击",
        "泄露": "敏感信息泄露",
        "rce": "远程代码执行",
        "文件包含": "文件包含攻击",
    }
    
    for keyword, threat_type in keywords_map.items():
        if keyword in value_lower:
            return threat_type
    
    return "其他"


def _apply_threat_mapping(json_obj: dict, mapping_dict: dict) -> dict:
    """应用威胁类型映射"""
    result = json_obj.copy()
    
    def find_and_add_mappings(obj):
        if isinstance(obj, dict):
            if 'normalize' in obj and isinstance(obj['normalize'], list):
                _process_normalize_array(obj['normalize'])
            
            for key, value in obj.items():
                find_and_add_mappings(value)
                
        elif isinstance(obj, list):
            for item in obj:
                find_and_add_mappings(item)
    
    def _process_normalize_array(normalize_array: list):
        for norm_item in normalize_array:
            if not isinstance(norm_item, dict):
                continue
            
            field_name = norm_item.get('field', '')
            
            if field_name != 'threat_type':
                continue
            
            mappings = norm_item.get('mappings', [])
            if mappings is None:
                mappings = []
                norm_item['mappings'] = mappings
            
            existing_org_values = {m.get('orgValue', '') for m in mappings if isinstance(m, dict)}
            
            for org_value, mapping_value in mapping_dict.items():
                if org_value not in existing_org_values:
                    mappings.append({
                        "mappingType": "REGULAR",
                        "mappingValue": mapping_value,
                        "orgValue": org_value
                    })
                    existing_org_values.add(org_value)
            
            break
    
    find_and_add_mappings(result)
    return result
