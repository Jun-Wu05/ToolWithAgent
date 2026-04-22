# -*- coding: utf-8 -*-
"""从日志文件中按字段键和正则逐行提取匹配的非重复值"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Optional


def extract_field_values(
    log_content: str,
    field_key: str,
    pattern: Optional[str] = None
) -> dict:
    """
    从日志内容中按字段提取非重复值
    
    Args:
        log_content: 日志文件内容（字符串）
        field_key: 要提取的字段名（作为 field 字段的值）
        pattern: 正则表达式，默认使用 'field_key"\s*:\s*"([^"]*)"'
        
    Returns:
        dict: {
            "status": "success" | "error",
            "field_key": str,           # 字段名
            "pattern": str,              # 使用的正则
            "unique_values": list[str],  # 非重复值列表
            "total_count": int,          # 原始匹配数
            "unique_count": int,         # 非重复数
            "matched_samples": dict,     # 每个值对应的样例日志
            "unmatched_count": int,       # 未匹配行数
            "error_message": str         # 错误信息（如果失败）
        }
    """
    try:
        # 处理换行符，统一为行列表
        log_lines = log_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        log_lines = [line.rstrip('\n') for line in log_lines if line.strip()]
        
        if not log_lines:
            return {
                "status": "error",
                "field_key": field_key,
                "pattern": pattern or "",
                "error_message": "日志内容为空"
            }
        
        # 默认正则：匹配 "field_key": "value" 格式
        if not pattern:
            pattern = fr'["\']{re.escape(field_key)}["\']\s*:\s*["\']([^"\']*?)["\']'
        
        # 预编译正则
        regex = re.compile(pattern)
        unique_values = OrderedDict()
        value_samples = OrderedDict()  # value -> first matched line
        matched_count = 0
        
        for raw_line in log_lines:
            # 快速过滤：字段key不在行中则跳过
            if field_key not in raw_line:
                continue
                
            line = raw_line.strip()
            if not line:
                continue
            
            # 查找匹配
            matches = regex.findall(line)
            if not matches:
                continue
            
            matched_count += 1
            
            # 处理匹配结果
            for match in matches:
                if isinstance(match, tuple):
                    match_value = next((item for item in match if item), "")
                else:
                    match_value = match
                
                if match_value and match_value not in unique_values:
                    unique_values[match_value] = None
                    value_samples[match_value] = raw_line
        
        unmatched_count = len(log_lines) - matched_count
        
        return {
            "status": "success",
            "field_key": field_key,
            "pattern": pattern,
            "unique_values": list(unique_values.keys()),
            "total_count": matched_count,
            "unique_count": len(unique_values),
            "matched_samples": dict(value_samples),
            "unmatched_count": unmatched_count
        }
        
    except Exception as e:
        return {
            "status": "error",
            "field_key": field_key,
            "pattern": pattern or "",
            "error_message": str(e)
        }


def generate_mapping_table(
    field_key: str,
    unique_values: list[str],
    mapping_type: str = "EQUAL"
) -> list[dict]:
    """
    根据提取的值生成映射表
    
    Args:
        field_key: 字段名（作为 field 值）
        unique_values: 提取的非重复值列表
        mapping_type: mappingType，默认 EQUAL
        
    Returns:
        list[dict]: 映射表，每项包含 {mappingType, orgValue, mappingValue, field}
    """
    return [
        {
            "mappingType": mapping_type,
            "orgValue": value,
            "mappingValue": "",  # 待用户填写
            "field": field_key
        }
        for value in unique_values
    ]


def save_mapping_to_excel(mapping_table: list[dict], output_path: str) -> str:
    """
    将映射表保存为 Excel 文件
    
    Args:
        mapping_table: 映射表列表
        output_path: 输出文件路径
        
    Returns:
        str: 输出文件路径
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "映射表"
    
    # 表头样式
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    
    # 边框样式
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # 写入表头
    headers = ["mappingType", "orgValue", "mappingValue", "field"]
    ws.append(headers)
    
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # 写入数据
    for row_data in mapping_table:
        row = [
            row_data.get("mappingType", "EQUAL"),
            row_data.get("orgValue", ""),
            row_data.get("mappingValue", ""),
            row_data.get("field", "")
        ]
        ws.append(row)
    
    # 设置列宽
    ws.column_dimensions['A'].width = 15  # mappingType
    ws.column_dimensions['B'].width = 30  # orgValue
    ws.column_dimensions['C'].width = 30  # mappingValue
    ws.column_dimensions['D'].width = 20  # field
    
    # 设置边框和对齐
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=4):
        for cell in row:
            cell.border = thin_border
            if row[0].row != 1:
                cell.alignment = Alignment(horizontal="left", vertical="center")
    
    wb.save(output_path)
    return output_path
