"""
威胁类型枚举字段处理工具

复用 src/threat_type_manager.py 的核心逻辑
"""
import json
import base64
import os
from typing import Any, Optional
import sys

# 添加项目根目录到路径，以便导入 ThreatTypeManager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.threat_type_manager import ThreatTypeManager


def get_default_threat_types() -> list:
    """获取默认的威胁类型列表"""
    return [
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


def load_threat_types_from_config() -> list:
    """
    从 config/threat_type_config.json 加载威胁类型列表
    
    Returns:
        list: 威胁类型名称列表
    """
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config",
        "threat_type_config.json"
    )
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                threat_types = config.get('threat_types', [])
                return [tt.get('name') for tt in threat_types if tt.get('name')]
        except Exception as e:
            print(f"加载威胁类型配置失败: {e}")
    
    return get_default_threat_types()


def parse_threat_mapping_table(markdown_table: str) -> list:
    """
    解析 Markdown 格式的威胁类型映射表
    
    Args:
        markdown_table: Agent 返回的 Markdown 格式映射表
        
    Returns:
        list: 映射关系列表 [{"mappingType": "REGULAR", "orgValue": "xxx", "mappingValue": "yyy"}, ...]
    """
    mappings = []
    
    lines = markdown_table.strip().split('\n')
    for line in lines:
        line = line.strip()
        # 跳过空行、header行、分隔线
        if not line or '---' in line:
            continue
        
        # 检查是否是表格行
        if line.startswith('|'):
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            if len(cells) >= 3:
                mapping_type = cells[0]
                org_value = cells[1]
                mapping_value = cells[2]
                
                # 只处理 REGULAR 类型的映射
                if mapping_type == "REGULAR" and org_value and mapping_value:
                    mappings.append({
                        "mappingType": mapping_type,
                        "orgValue": org_value,
                        "mappingValue": mapping_value
                    })
    
    return mappings


def parse_threat_mapping_table_from_df(df) -> list:
    """
    从 DataFrame 解析威胁类型映射表
    
    Args:
        df: pandas DataFrame，包含 mappingType, orgValue, mappingValue 列
        
    Returns:
        list: 映射关系列表
    """
    mappings = []
    
    for _, row in df.iterrows():
        mapping_type = row.get("mappingType", "REGULAR")
        org_value = row.get("orgValue", "")
        mapping_value = row.get("mappingValue", "")
        
        if mapping_type == "REGULAR" and org_value and mapping_value:
            mappings.append({
                "mappingType": mapping_type,
                "orgValue": org_value,
                "mappingValue": mapping_value
            })
    
    return mappings


def generate_threat_type_mapping_table(
    decoded_json: dict,
    excel_template_path: Optional[str] = None
) -> dict:
    """
    生成威胁类型映射表
    
    Args:
        decoded_json: 解码后的 JSON 对象
        excel_template_path: 可选，Excel 模板路径（config/对象.xlsx）
        
    Returns:
        dict: 包含映射结果
            - threat_values: 提取到的威胁类型值列表
            - suggested_mappings: 建议的映射表
            - all_threat_types: 所有可用的威胁类型
            - status: "success" | "error"
    """
    try:
        # 初始化 ThreatTypeManager
        threat_manager = ThreatTypeManager()
        
        # 获取所有配置的威胁类型
        all_threat_types = threat_manager.get_all_threat_types()
        
        # 从 JSON 中提取威胁类型值
        threat_values = extract_threat_values(decoded_json)
        
        # 生成建议的映射
        suggested_mappings = []
        for threat_value in threat_values:
            # 使用 ThreatTypeManager 进行匹配
            matched_type = threat_manager.find_matching_threat_type(threat_value, mapping_type='REGULAR')
            suggested_mappings.append({
                "mappingType": "REGULAR",
                "orgValue": threat_value,
                "mappingValue": matched_type,
                "matchStatus": "自动匹配" if matched_type != threat_manager.default_type else "需要确认"
            })
        
        return {
            "status": "success",
            "threat_values": threat_values,
            "suggested_mappings": suggested_mappings,
            "all_threat_types": all_threat_types,
            "default_type": threat_manager.default_type
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"生成威胁类型映射表失败: {str(e)}"
        }


def extract_threat_values(json_obj: dict) -> list:
    """
    从 JSON 对象中提取威胁类型值
    
    Args:
        json_obj: JSON 对象
        
    Returns:
        list: 威胁类型值列表
    """
    threat_values = []
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            # 检查常见的威胁类型字段名
            threat_field_names = ['threatType', 'threat_type', 'alertType', 'attackType', 'threat', 'category']
            
            for field_name in threat_field_names:
                if field_name in obj and obj[field_name]:
                    value = obj[field_name]
                    if isinstance(value, str) and value.strip():
                        if value not in threat_values:
                            threat_values.append(value)
            
            # 继续遍历
            for key, value in obj.items():
                traverse(value, f"{path}.{key}" if path else key)
                
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(json_obj)
    return threat_values


def apply_threat_type_mapping(
    json_obj: dict,
    mapping_table: list,
    excel_template_path: Optional[str] = None
) -> dict:
    """
    应用威胁类型映射到 JSON 对象
    按照 GUI 逻辑：将映射关系添加到 normalize 数组中
    
    Args:
        json_obj: 解码后的 JSON 对象
        mapping_table: 映射表，格式为:
            [
                {"mappingType": "REGULAR", "orgValue": "xxx", "mappingValue": "yyy"},
                ...
            ]
        excel_template_path: 可选，Excel 模板路径
        
    Returns:
        dict: 修改后的 JSON 对象
    """
    result = json_obj.copy()
    
    # 构建映射索引：orgValue -> mappingItem
    mapping_dict = {}
    for item in mapping_table:
        mapping_type = item.get("mappingType", "")
        org_value = item.get("orgValue", "")
        mapping_value = item.get("mappingValue", "")
        
        if mapping_type == "REGULAR" and org_value and mapping_value:
            mapping_dict[org_value] = item
    
    if not mapping_dict:
        print("[WARNING] 映射表为空，无需处理")
        return result
    
    # 遍历 JSON 找到 normalize 数组
    def find_and_add_mappings(obj):
        """递归遍历 JSON，找到 normalize 数组并添加映射"""
        if isinstance(obj, dict):
            # 检查是否是 normalize 数组
            if 'normalize' in obj and isinstance(obj['normalize'], list):
                _process_normalize_array(obj['normalize'])
            
            # 继续遍历
            for key, value in obj.items():
                find_and_add_mappings(value)
                
        elif isinstance(obj, list):
            for item in obj:
                find_and_add_mappings(item)
    
    def _process_normalize_array(normalize_array: list):
        """处理 normalize 数组，找到 threat_type 字段并添加映射"""
        for norm_item in normalize_array:
            if not isinstance(norm_item, dict):
                continue
            
            field_name = norm_item.get('field', '')
            
            # 只处理 threat_type 字段
            if field_name != 'threat_type':
                continue
            
            # 获取或创建 mappings 数组
            mappings = norm_item.get('mappings', [])
            if mappings is None:
                mappings = []
                norm_item['mappings'] = mappings
            
            # 获取已存在的 orgValue 集合
            existing_org_values = {m.get('orgValue', '') for m in mappings if isinstance(m, dict)}
            
            # 添加新的映射（去重）
            added_count = 0
            updated_count = 0
            
            for org_value, mapping_item in mapping_dict.items():
                if org_value in existing_org_values:
                    # 更新已存在的映射
                    for existing_m in mappings:
                        if isinstance(existing_m, dict) and existing_m.get('orgValue') == org_value:
                            existing_mv = existing_m.get('mappingValue', '')
                            new_mv = mapping_item.get('mappingValue', '')
                            if new_mv and existing_mv != new_mv:
                                existing_m['mappingValue'] = new_mv
                                updated_count += 1
                                print(f"更新映射: {org_value} -> {new_mv}")
                            break
                else:
                    # 添加新映射
                    mappings.append({
                        "mappingType": mapping_item.get("mappingType", "REGULAR"),
                        "mappingValue": mapping_item.get("mappingValue", ""),
                        "orgValue": mapping_item.get("orgValue", "")
                    })
                    existing_org_values.add(org_value)
                    added_count += 1
                    print(f"添加映射: {org_value} -> {mapping_item.get('mappingValue', '')}")
            
            print(f"[INFO] normalize 数组处理完成: 新增 {added_count} 个映射, 更新 {updated_count} 个映射")
            break  # 只处理第一个 threat_type 字段
    
    # 执行映射添加
    find_and_add_mappings(result)
    
    return result


def json_to_threat_mapping_txt(
    json_obj: dict,
    mapping_table: list
) -> str:
    """
    将 JSON 和映射表转换为威胁类型映射的 txt 格式
    
    Args:
        json_obj: 处理后的 JSON 对象
        mapping_table: 映射表
        
    Returns:
        str: txt 格式的威胁类型映射
    """
    lines = []
    lines.append("threatType mapping:")
    
    for item in mapping_table:
        mapping_type = item.get("mappingType", "REGULAR")
        org_value = item.get("orgValue", "")
        mapping_value = item.get("mappingValue", "")
        
        if mapping_type == "REGULAR":
            lines.append(f"  {org_value} -> {mapping_value}")
    
    return "\n".join(lines)


def process_threat_type_workflow(
    base64_data: str,
    mapping_table: list
) -> dict:
    """
    完整的威胁类型处理流程
    
    Args:
        base64_data: Base64 编码的数据
        mapping_table: 映射表
        
    Returns:
        dict: 处理结果
            - status: "success" | "error"
            - decoded_json: 解码后的 JSON
            - processed_json: 处理后的 JSON
            - txt_output: txt 格式输出
    """
    try:
        # 1. 解码 Base64
        decoded_bytes = base64.b64decode(base64_data)
        decoded_json = json.loads(decoded_bytes.decode('utf-8'))
        
        # 2. 应用威胁类型映射
        processed_json = apply_threat_type_mapping(decoded_json, mapping_table)
        
        # 3. 生成 txt 输出
        txt_output = json_to_threat_mapping_txt(processed_json, mapping_table)
        
        return {
            "status": "success",
            "decoded_json": decoded_json,
            "processed_json": processed_json,
            "txt_output": txt_output
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"威胁类型处理失败: {str(e)}"
        }


if __name__ == "__main__":
    # 测试代码
    print("威胁类型工具测试")
    
    # 测试加载威胁类型
    all_types = load_threat_types_from_config()
    print(f"加载到 {len(all_types)} 个威胁类型")
    print(all_types[:5])
