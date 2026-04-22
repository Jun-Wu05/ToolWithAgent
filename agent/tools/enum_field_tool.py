"""
普通字段枚举处理工具

功能：
- 解码 Base64 编码的配置文件
- 提取 JSON 中的 simEntities 数组和可枚举字段
- 生成 Excel 格式的字段映射模板
- 根据映射表修改 normalize 数组中的字段值
- 输出修改后的 JSON 配置
"""
import json
import base64
import os
from typing import Any, Optional
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


def decode_enum_config(b64_text: str) -> dict:
    """
    解码 Base64 枚举配置并提取关键信息
    
    Args:
        b64_text: Base64 编码的配置文件
        
    Returns:
        dict: 解码结果
            - status: "success" | "error"
            - decoded_json: 解码后的 JSON 对象
            - sim_entities: simEntities 数组
            - normalize_fields: normalize 数组中的字段列表
            - enum_candidates: 可枚举的字段候选列表
    """
    try:
        # 清理并解码
        cleaned = "".join(b64_text.split())
        if not cleaned:
            return {"status": "error", "error_message": "输入为空"}
        
        # 补齐 padding
        missing_padding = len(cleaned) % 4
        if missing_padding:
            cleaned += "=" * (4 - missing_padding)
        
        # 解码
        decoded_bytes = base64.b64decode(cleaned)
        decoded_text = decoded_bytes.decode("utf-8", errors="replace")
        
        # 解析 JSON
        decoded_json = json.loads(decoded_text)
        
        # 提取 simEntities
        sim_entities = extract_sim_entities(decoded_json)
        
        # 提取 normalize 字段
        normalize_fields = extract_normalize_fields(decoded_json)
        
        # 识别可枚举的字段
        enum_candidates = identify_enum_candidates(decoded_json, normalize_fields)
        
        return {
            "status": "success",
            "decoded_json": decoded_json,
            "decoded_text": decoded_text,
            "sim_entities": sim_entities,
            "normalize_fields": normalize_fields,
            "enum_candidates": enum_candidates,
            "field_count": len(normalize_fields)
        }
        
    except Exception as e:
        return {"status": "error", "error_message": f"解码失败: {str(e)}"}


def extract_sim_entities(json_obj: dict) -> list:
    """
    递归提取 JSON 中的 simEntities 数组
    
    Args:
        json_obj: JSON 对象
        
    Returns:
        list: simEntities 数组列表
    """
    sim_entities_list = []
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            if "simEntities" in obj and isinstance(obj["simEntities"], list):
                sim_entities_list.append({
                    "path": path or "root",
                    "simEntities": obj["simEntities"]
                })
            
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key
                traverse(value, new_path)
                
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                traverse(item, f"{path}[{i}]")
    
    traverse(json_obj)
    return sim_entities_list


def extract_normalize_fields(json_obj: dict) -> list:
    """
    提取 normalize 数组中的所有字段信息
    
    Args:
        json_obj: JSON 对象
        
    Returns:
        list: 字段信息列表 [{index, field, entity, result}, ...]
    """
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
                            "core": item.get("core", False),
                            "sim": item.get("sim", False)
                        }
                        fields.append(field_info)
            
            for value in obj.values():
                traverse(value)
                
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)
    
    traverse(json_obj)
    return fields


def identify_enum_candidates(json_obj: dict, normalize_fields: list) -> list:
    """
    识别可枚举的字段候选
    
    Args:
        json_obj: JSON 对象
        normalize_fields: normalize 字段列表
        
    Returns:
        list: 可枚举的字段列表 [{field, values, count}, ...]
    """
    candidates = []
    
    # 统计每个 field 的唯一值
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
    
    # 生成候选列表
    for field, values in field_values.items():
        if len(values) > 1:  # 至少有2个不同值才有枚举必要
            candidates.append({
                "field": field,
                "values": sorted(list(values)),
                "count": len(values)
            })
    
    return candidates


def generate_enum_mapping_template(
    decoded_json: dict,
    excel_path: Optional[str] = None,
    target_field: Optional[str] = None
) -> dict:
    """
    生成枚举字段映射模板
    
    Args:
        decoded_json: 解码后的 JSON 对象
        excel_path: 可选，Excel 模板保存路径
        target_field: 可选，指定目标字段
        
    Returns:
        dict: 生成结果
            - status: "success" | "error"
            - mapping_table: 映射表数据
            - excel_path: Excel 文件路径（如果生成了）
    """
    try:
        # 提取 normalize 字段
        normalize_fields = extract_normalize_fields(decoded_json)
        
        # 构建映射表
        mapping_table = []
        
        for item in normalize_fields:
            field = item.get("field", "")
            index = item.get("index", "")
            result = item.get("result", [])
            mappings = item.get("mappings", [])
            
            # 如果指定了目标字段，只处理该字段
            if target_field and field != target_field:
                continue
            
            # 获取当前映射
            existing_mappings = {}
            if isinstance(mappings, list):
                for m in mappings:
                    if isinstance(m, dict):
                        org = m.get("orgValue", "")
                        mv = m.get("mappingValue", "")
                        if org:
                            existing_mappings[org] = mv
            
            # 处理 result 值
            if isinstance(result, list):
                for v in result:
                    if v and str(v).strip():
                        v_str = str(v).strip()
                        mapping_table.append({
                            "field": field,
                            "index": index,
                            "orgValue": v_str,
                            "mappingValue": existing_mappings.get(v_str, ""),
                            "mappingType": "REGULAR"
                        })
            elif result:
                v_str = str(result).strip()
                mapping_table.append({
                    "field": field,
                    "index": index,
                    "orgValue": v_str,
                    "mappingValue": existing_mappings.get(v_str, ""),
                    "mappingType": "REGULAR"
                })
        
        # 生成 Excel 文件
        if excel_path:
            save_mapping_to_excel(mapping_table, excel_path)
        
        return {
            "status": "success",
            "mapping_table": mapping_table,
            "excel_path": excel_path,
            "record_count": len(mapping_table)
        }
        
    except Exception as e:
        return {"status": "error", "error_message": f"生成映射模板失败: {str(e)}"}


def save_mapping_to_excel(mapping_table: list, excel_path: str) -> bool:
    """
    将映射表保存为 Excel 文件
    
    Args:
        mapping_table: 映射表数据
        excel_path: Excel 文件保存路径
        
    Returns:
        bool: 是否保存成功
    """
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "枚举映射"
        
        # 设置表头样式
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center")
        
        # 写入表头
        headers = ["mappingType", "orgValue", "mappingValue", "field"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment
        
        # 设置边框
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # 写入数据
        for row_idx, item in enumerate(mapping_table, 2):
            ws.cell(row=row_idx, column=1, value=item.get("mappingType", "REGULAR"))
            ws.cell(row=row_idx, column=2, value=item.get("orgValue", ""))
            ws.cell(row=row_idx, column=3, value=item.get("mappingValue", ""))
            ws.cell(row=row_idx, column=4, value=item.get("field", ""))
            
            # 应用边框
            for col in range(1, 5):
                ws.cell(row=row_idx, column=col).border = thin_border
        
        # 自动调整列宽
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column].width = adjusted_width
        
        # 保存文件
        wb.save(excel_path)
        return True
        
    except Exception as e:
        print(f"保存 Excel 失败: {e}")
        return False


def load_mapping_from_excel(excel_path: str) -> list:
    """
    从 Excel 文件加载映射表（新格式）
    
    格式说明：
    - 每个 Sheet 的标签名 = 目标字段名（可以是 normalize 的 index 值或 field 值）
    - Sheet 内部三列：mappingType | orgValue | mappingValue
    
    Args:
        excel_path: Excel 文件路径
        
    Returns:
        list: 映射表数据 [{"mappingType": "REGULAR", "orgValue": "xxx", "mappingValue": "yyy", "field": "目标字段名"}, ...]
    """
    from openpyxl import load_workbook
    
    mapping_table = []
    
    try:
        wb = load_workbook(excel_path, data_only=True)
        
        # 遍历所有 Sheet
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            field_name = sheet_name.strip()  # Sheet 名就是目标字段名
            
            # 跳过表头，从第二行开始读取
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0] and row[1]:  # mappingType 和 orgValue 必须有值
                    mapping_table.append({
                        "mappingType": str(row[0]).strip() if row[0] else "REGULAR",
                        "orgValue": str(row[1]).strip() if row[1] else "",
                        "mappingValue": str(row[2]).strip() if row[2] else "",
                        "field": field_name
                    })
        
        wb.close()
        print(f"加载映射表：{len(mapping_table)} 条记录，{len(wb.sheetnames)} 个字段")
        
    except Exception as e:
        print(f"读取 Excel 失败: {e}")
    
    return mapping_table


def apply_enum_mapping(
    json_obj: dict,
    mapping_table: list,
    target_field: Optional[str] = None
) -> dict:
    """
    应用枚举映射到 JSON 对象
    
    Args:
        json_obj: 原始 JSON 对象
        mapping_table: 映射表，格式为:
            [
                {"mappingType": "REGULAR", "orgValue": "xxx", "mappingValue": "yyy", "field": "zzz"},
                ...
            ]
        target_field: 可选，指定目标字段
        
    Returns:
        dict: 修改后的 JSON 对象
    """
    result = json_obj.copy()
    
    # 按字段分组映射
    field_mappings = {}
    for item in mapping_table:
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
    
    if not field_mappings:
        print("[WARNING] 映射表为空或字段不匹配")
        return result
    
    # 应用映射
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            # 处理 normalize 数组
            if "normalize" in obj and isinstance(obj["normalize"], list):
                for norm_item in obj["normalize"]:
                    if isinstance(norm_item, dict):
                        field = norm_item.get("field", "")
                        
                        # 如果指定了目标字段，只处理该字段
                        if target_field and field != target_field:
                            continue
                        
                        if field in field_mappings:
                            # 获取或创建 mappings 数组
                            mappings = norm_item.get("mappings", [])
                            if mappings is None:
                                mappings = []
                                norm_item["mappings"] = mappings
                            
                            # 获取已存在的映射
                            existing_org_values = {m.get("orgValue", "") for m in mappings if isinstance(m, dict)}
                            
                            # 添加/更新映射
                            for org_value, mapping_value in field_mappings[field].items():
                                if org_value not in existing_org_values:
                                    mappings.append({
                                        "mappingType": "REGULAR",
                                        "orgValue": org_value,
                                        "mappingValue": mapping_value
                                    })
                                    print(f"添加映射 [{field}]: {org_value} -> {mapping_value}")
            
            # 继续遍历
            for key, value in obj.items():
                traverse(value, f"{path}.{key}" if path else key)
                
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(result)
    return result


def process_enum_workflow(
    base64_data: str,
    mapping_table: list,
    target_field: Optional[str] = None
) -> dict:
    """
    完整的枚举字段处理流程
    
    Args:
        base64_data: Base64 编码的数据
        mapping_table: 映射表
        target_field: 可选，指定目标字段
        
    Returns:
        dict: 处理结果
            - status: "success" | "error"
            - decoded_json: 解码后的 JSON
            - processed_json: 处理后的 JSON
            - json_output: JSON 格式输出
    """
    try:
        # 1. 解码 Base64
        decoded_bytes = base64.b64decode(base64_data)
        decoded_json = json.loads(decoded_bytes.decode('utf-8'))
        
        # 2. 应用枚举映射
        processed_json = apply_enum_mapping(decoded_json, mapping_table, target_field)
        
        # 3. 生成 JSON 输出
        json_output = json.dumps(processed_json, ensure_ascii=False, indent=2)
        
        return {
            "status": "success",
            "decoded_json": decoded_json,
            "processed_json": processed_json,
            "json_output": json_output
        }
        
    except Exception as e:
        return {"status": "error", "error_message": f"枚举字段处理失败: {str(e)}"}


def get_enum_fields_list(enum_candidates: list) -> str:
    """
    生成枚举候选字段的可读列表
    
    Args:
        enum_candidates: 可枚举字段候选列表
        
    Returns:
        str: 格式化后的字段列表
    """
    if not enum_candidates:
        return "未发现可枚举的字段"
    
    lines = ["可枚举字段列表：", ""]
    for i, candidate in enumerate(enum_candidates, 1):
        field = candidate.get("field", "未知")
        values = candidate.get("values", [])
        count = candidate.get("count", 0)
        
        lines.append(f"{i}. **{field}**")
        lines.append(f"   - 唯一值数量: {count}")
        lines.append(f"   - 示例值: {', '.join(values[:3])}" + ("..." if len(values) > 3 else ""))
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试代码
    print("枚举字段工具测试")
    
    # 测试解码
    test_b64 = "test"
    result = decode_enum_config(test_b64)
    print(f"解码结果: {result['status']}")
