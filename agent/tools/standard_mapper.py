"""
标准字段映射 + Excel 填充工具

复用 src/handlers/standard_field_mapping_handler.py 的核心逻辑
"""
import json
import base64
from typing import Any, Optional
from openpyxl import load_workbook
from collections import defaultdict


def standard_field_mapping(
    decoded_json: dict,
    field_mapping_table: list[dict],
    excel_template_path: Optional[str] = None
) -> dict:
    """
    Agno Tool: 执行标准字段映射并生成 Excel 填充数据
    
    Args:
        decoded_json: 解码后的 JSON 对象
        field_mapping_table: 字段映射表，格式为:
            [
                {"原始字段名": "content.srcip", "系统属性名称": "源地址", "匹配状态": "匹配成功"},
                ...
            ]
        excel_template_path: 可选，Excel 模板路径（config/对象.xlsx）
        
    Returns:
        dict: 包含映射结果
            - processed_json: 映射后的 JSON 对象
            - excel_data: Excel 填充数据
            - entities_added: 添加到 simEntities 的实体列表
            - status: "success" | "partial" | "error"
    """
    try:
        # 1. 读取 Excel 模板的"对应关系" Sheet
        object_mapping = {}
        if excel_template_path:
            object_mapping = load_object_mapping(excel_template_path)
        
        # 2. 解析字段映射表，建立字段与对象的映射
        field_to_object = {}
        field_to_new_value = {}
        
        for mapping in field_mapping_table:
            original_field = mapping.get("原始字段名", "")
            system_property = mapping.get("系统属性名称", "")
            match_status = mapping.get("匹配状态", "")
            
            # 只处理匹配成功的映射
            if "匹配成功" in match_status:
                # 从对象映射表中查找对象
                obj = object_mapping.get(system_property, "事件")  # 默认对象
                field_to_object[original_field] = obj
                field_to_new_value[original_field] = system_property
        
        # 3. 修改 JSON 中的 normalize 数组
        processed_json = apply_field_mapping(decoded_json, field_to_new_value)
        
        # 4. 管理 simEntities 数组
        entities_added = manage_sim_entities(processed_json, field_to_object)
        
        return {
            "status": "success",
            "processed_json": processed_json,
            "excel_data": generate_excel_data(field_mapping_table),
            "entities_added": entities_added,
            "fields_mapped": len(field_to_new_value)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"标准字段映射失败: {str(e)}"
        }


def load_object_mapping(excel_path: str) -> dict:
    """
    读取 Excel 模板的"对应关系" Sheet，建立系统属性名称到对象的映射
    
    Args:
        excel_path: Excel 文件路径
        
    Returns:
        dict: {系统属性名称: 对象}
    """
    mapping = {}
    try:
        wb = load_workbook(excel_path, data_only=True)
        if "对应关系" in wb.sheetnames:
            ws = wb["对应关系"]
            # 假设格式：系统属性名称 | 字段名称 | 对象
            for row in ws.iter_rows(min_row=2, values_only=True):
                if len(row) >= 3 and row[0] and row[2]:
                    system_property = str(row[0]).strip()
                    obj = str(row[2]).strip()
                    mapping[system_property] = obj
    except Exception as e:
        print(f"读取 Excel 失败: {e}")
    return mapping


def apply_field_mapping(json_obj: dict, field_mapping: dict, field_to_object: dict = None, prop_to_field: dict = None) -> dict:
    """
    应用字段映射到 JSON 对象（复用 Tkinter 版本的核心逻辑）
    
    Args:
        json_obj: 原始 JSON 对象
        field_mapping: {原始字段名: 新值（系统属性名称或字段名称）}
        field_to_object: {字段名称: 对象类型}，从 Excel 映射表获取
        prop_to_field: {系统属性名称: 字段名称}，从 Excel 映射表获取
        
    Returns:
        dict: 修改后的 JSON 对象
    """
    result = json_obj.copy()
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            # 检查是否有 normalize 数组，这是需要修改的主要位置
            if "normalize" in obj and isinstance(obj["normalize"], list):
                for item in obj["normalize"]:
                    if isinstance(item, dict):
                        # 获取原始字段名（index 字段）
                        original_index = str(item.get("index", "") or "").strip().lower()
                        # 获取 result 字段的值作为备选匹配
                        result_values = item.get("result", [])
                        if isinstance(result_values, list):
                            result_values_lower = [str(v).strip().lower() for v in result_values if v is not None]
                        else:
                            result_values_lower = [str(result_values).strip().lower()]
                        
                        # 遍历映射表查找匹配项
                        matched = False
                        for original_field, mapped_field in field_mapping.items():
                            original_lower = str(original_field).strip().lower()
                            
                            # 匹配逻辑：按 index、field、result 顺序匹配
                            if (original_lower == original_index or 
                                original_lower in original_index or
                                original_lower in result_values_lower):
                                
                                # 转换系统属性名称为字段名称（如果需要）
                                final_field = mapped_field
                                entity = "事件"  # 默认对象
                                
                                if prop_to_field and mapped_field in prop_to_field:
                                    final_field = prop_to_field[mapped_field]
                                
                                # 从 field_to_object 获取对象类型
                                if field_to_object and final_field in field_to_object:
                                    entity = field_to_object[final_field]
                                
                                # 更新 normalize 项的多个字段（复用 Tkinter 逻辑）
                                item["field"] = final_field
                                item["entity"] = entity
                                item["core"] = False
                                item["sim"] = True
                                
                                # 保持原来的 result 数据值不变
                                matched = True
                                print(f"映射成功: {original_field} -> {final_field} (entity: {entity})")
                                break
                        
                        # 如果没有匹配到，尝试通过原始 index 匹配
                        if not matched and original_index in field_mapping:
                            mapped_field = field_mapping[original_index]
                            final_field = mapped_field
                            entity = "事件"
                            
                            if prop_to_field and mapped_field in prop_to_field:
                                final_field = prop_to_field[mapped_field]
                            
                            if field_to_object and final_field in field_to_object:
                                entity = field_to_object[final_field]
                            
                            item["field"] = final_field
                            item["entity"] = entity
                            item["core"] = False
                            item["sim"] = True
                            print(f"映射成功（index匹配）: {original_index} -> {final_field} (entity: {entity})")
            
            # 继续遍历
            for key, value in obj.items():
                if key != "normalize":  # 跳过 normalize 因为已经处理过
                    traverse(value, f"{path}.{key}" if path else key)
                    
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(result)
    return result


def manage_sim_entities(json_obj: dict, field_to_object: dict) -> list:
    """
    管理 simEntities 数组，添加新的实体
    
    Args:
        json_obj: JSON 对象
        field_to_object: {字段名: 对象}
        
    Returns:
        list: 添加的实体列表
    """
    entities_added = []
    
    # 获取所有需要添加的对象类型
    objects_needed = set(field_to_object.values())
    
    def find_or_create_sim_entities(obj):
        nonlocal entities_added
        
        if isinstance(obj, dict):
            # 找到 simEntities 数组
            if "simEntities" in obj and isinstance(obj["simEntities"], list):
                sim_entities = obj["simEntities"]
                existing_objects = {e.get("object") for e in sim_entities if isinstance(e, dict)}
                
                # 添加缺失的对象
                for obj_type in objects_needed:
                    if obj_type not in existing_objects:
                        new_entity = {
                            "object": obj_type,
                            "fields": []
                        }
                        sim_entities.append(new_entity)
                        entities_added.append(obj_type)
                        
            # 递归继续查找
            for value in obj.values():
                find_or_create_sim_entities(value)
                
        elif isinstance(obj, list):
            for item in obj:
                find_or_create_sim_entities(item)
    
    find_or_create_sim_entities(json_obj)
    return entities_added


def generate_excel_data(field_mapping_table: list[dict]) -> list[dict]:
    """
    生成 Excel 填充数据
    
    Args:
        field_mapping_table: 字段映射表
        
    Returns:
        list: Excel 数据
    """
    excel_data = []
    
    for mapping in field_mapping_table:
        excel_data.append({
            "原始字段名": mapping.get("原始字段名", ""),
            "系统属性名称": mapping.get("系统属性名称", ""),
            "mappingType": "REGULAR",
            "orgValue": ".*",  # 默认正则表达式
            "mappingValue": mapping.get("系统属性名称", "")
        })
    
    return excel_data


def load_full_object_mapping(excel_path: str) -> tuple:
    """
    读取 Excel 模板的【对应关系】Sheet，建立完整的映射关系
    
    Args:
        excel_path: Excel 文件路径
        
    Returns:
        tuple: (prop_to_field, field_to_entity)
            - prop_to_field: {系统属性名称: 字段名称}
            - field_to_entity: {字段名称: 对象类型}
    """
    prop_to_field = {}  # 系统属性名称 -> 字段名称
    field_to_entity = {}  # 字段名称 -> 对象类型
    
    try:
        wb = load_workbook(excel_path, data_only=True)
        if "对应关系" in wb.sheetnames:
            ws = wb["对应关系"]
            # 格式：系统属性名称 | 字段名称 | 对象
            for row in ws.iter_rows(min_row=2, values_only=True):
                if len(row) >= 3 and row[0] and row[1] and row[2]:
                    prop_name = str(row[0]).strip()
                    field_name = str(row[1]).strip()
                    entity_name = str(row[2]).strip()
                    
                    # 处理多个对象的情况，取第一个
                    if ',' in entity_name:
                        entity_name = entity_name.split(',')[0].strip()
                    
                    prop_to_field[prop_name] = field_name
                    field_to_entity[field_name] = entity_name
                    
            print(f"加载映射表: {len(prop_to_field)} 个系统属性映射, {len(field_to_entity)} 个字段实体映射")
        wb.close()
    except Exception as e:
        print(f"读取 Excel 映射表失败: {e}")
    
    return prop_to_field, field_to_entity


def apply_mapping_to_json(
    json_obj: dict,
    mapping_table: list[dict],
    sim_entities: list = None,
    excel_template_path: str = None
) -> dict:
    """
    根据映射表修改 JSON 中的 normalize 数组（复用 Tkinter 版本的完整逻辑）
    
    Args:
        json_obj: 解码后的 JSON 对象
        mapping_table: 映射表，格式为:
            [
                {"原始字段名": "xxx", "系统属性名称": "yyy"},
                ...
            ]
        sim_entities: simEntities 数组，用于添加新实体
        excel_template_path: Excel 模板路径（默认使用 config/对象.xlsx）
        
    Returns:
        dict: 修改后的 JSON 对象
    """
    result = json_obj.copy()
    
    # 解析映射表
    field_mappings = {}
    for item in mapping_table:
        original = item.get("原始字段名", "")
        target = item.get("系统属性名称", "")
        if original and target:
            field_mappings[original] = target
    
    # 加载 Excel 映射表获取 field_to_object 和 prop_to_field
    prop_to_field = {}
    field_to_entity = {}
    
    if excel_template_path is None:
        # 使用默认路径
        import os
        excel_template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "对象.xlsx")
    
    if os.path.exists(excel_template_path):
        prop_to_field, field_to_entity = load_full_object_mapping(excel_template_path)
    
    # 应用映射 - 传递完整的映射参数
    result = apply_field_mapping(result, field_mappings, field_to_entity, prop_to_field)
    
    # 管理 simEntities
    if sim_entities is not None:
        entities_added = manage_sim_entities(result, field_to_entity)
    
    return result


def parse_markdown_mapping_table(markdown_table: str) -> list:
    """
    解析 Markdown 格式的映射表，返回映射关系列表
    
    Args:
        markdown_table: Agent 返回的 Markdown 格式映射表
        
    Returns:
        list: 映射关系列表 [{"original": "xxx", "mapped": "yyy"}, ...]
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
            if len(cells) >= 2:
                original_field = cells[0]
                system_field = cells[1]
                status = cells[2] if len(cells) > 2 else ""
                
                # 只添加匹配成功的映射
                if "匹配成功" in status and original_field and system_field:
                    mappings.append({
                        "original": original_field,
                        "mapped": system_field
                    })
    
    return mappings