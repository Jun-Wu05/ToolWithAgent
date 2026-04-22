import json
import os
import sys
from collections import defaultdict
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side

def enum_json_to_md_table(json_data):
    """
    将枚举JSON转换为Markdown表格格式（单表）
    """
    md_lines = []
    md_lines.append("| mappingType | orgValue | mappingValue | field |")
    md_lines.append("|-------------|----------|--------------|-------|")
    
    for enum_item in json_data.get("enums", []):
        field_name = enum_item.get("enum_name_key", "")
        values = enum_item.get("values", {})
        
        for org_value, mapping_value in values.items():
            md_lines.append(f"| EQUAL | {org_value} | {mapping_value} | {field_name} |")
    
    return "\n".join(md_lines)


def enum_json_to_md_by_field(json_data):
    """
    将枚举JSON按field分组，生成多个Markdown表格
    """
    # 按field分组
    field_groups = defaultdict(list)
    
    for enum_item in json_data.get("enums", []):
        field_name = enum_item.get("enum_name_key", "")
        values = enum_item.get("values", {})
        
        for org_value, mapping_value in values.items():
            field_groups[field_name].append({
                "orgValue": org_value,
                "mappingValue": mapping_value
            })
    
    # 生成每个field的Markdown表格
    md_sections = []
    for field_name, items in field_groups.items():
        md_lines = []
        md_lines.append(f"## {field_name}\n")
        md_lines.append("| mappingType | orgValue | mappingValue |")
        md_lines.append("|-------------|----------|--------------|")
        
        for item in items:
            md_lines.append(f"| EQUAL | {item['orgValue']} | {item['mappingValue']} |")
        
        md_sections.append("\n".join(md_lines))
    
    return "\n\n".join(md_sections)


def enum_json_to_excel_by_field(json_data, output_path):
    """
    将枚举JSON转换为Excel文件，按field分Sheet页
    
    Args:
        json_data: 枚举JSON数据
        output_path: 输出Excel文件路径
    """
    # 创建工作簿
    wb = openpyxl.Workbook()
    
    # 删除默认的Sheet
    default_sheet = wb.active
    wb.remove(default_sheet)
    
    # 按field分组
    field_groups = defaultdict(list)
    
    for enum_item in json_data.get("enums", []):
        field_name = enum_item.get("enum_name_key", "")
        values = enum_item.get("values", {})
        
        for org_value, mapping_value in values.items():
            field_groups[field_name].append({
                "orgValue": org_value,
                "mappingValue": mapping_value
            })
    
    # 定义样式
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = openpyxl.styles.PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    cell_alignment = Alignment(horizontal="left", vertical="center")
    
    # 为每个field创建Sheet
    for field_name, items in field_groups.items():
        # Sheet名称处理：Excel Sheet名称不能超过31个字符，不能包含特殊字符
        sheet_name = field_name[:31]  # 截取前31个字符
        # 替换非法字符：/:?*[]\
        for char in ['/', ':', '?', '*', '[', ']', '\\']:
            sheet_name = sheet_name.replace(char, '_')
        
        ws = wb.create_sheet(title=sheet_name)
        
        # 设置表头
        headers = ["mappingType", "orgValue", "mappingValue"]
        ws.append(headers)
        
        # 设置表头样式
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
        
        # 添加数据行
        for item in items:
            ws.append(["EQUAL", item["orgValue"], item["mappingValue"]])
        
        # 设置列宽
        ws.column_dimensions['A'].width = 15  # mappingType
        ws.column_dimensions['B'].width = 20  # orgValue
        ws.column_dimensions['C'].width = 40  # mappingValue
        
        # 设置边框和对齐
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=3):
            for cell in row:
                cell.border = thin_border
                if row[0].row != 1:  # 非表头行
                    cell.alignment = cell_alignment
    
    # 保存文件
    wb.save(output_path)


def process_enum_file(input_filename, input_dir="data", output_dir="output"):
    """
    从data目录读取枚举JSON文件，输出Markdown表格txt和Excel文件到output目录
    
    Args:
        input_filename: 输入文件名（如 "enum_input.json"）
        input_dir: 输入目录，默认为 "data"
        output_dir: 输出目录，默认为 "output"
    """
    # 获取当前脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 构建完整路径
    input_path = os.path.join(script_dir, input_dir, input_filename)
    base_name = os.path.splitext(input_filename)[0]
    txt_output_path = os.path.join(script_dir, output_dir, f"{base_name}_converted.txt")
    txt_by_field_path = os.path.join(script_dir, output_dir, f"{base_name}_by_field.txt")
    excel_output_path = os.path.join(script_dir, output_dir, f"{base_name}_converted.xlsx")
    
    # 检查输入文件是否存在
    if not os.path.exists(input_path):
        print(f"错误：输入文件不存在 - {input_path}")
        return None
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(txt_output_path), exist_ok=True)
    
    # 读取输入文件
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 解析JSON
    try:
        enum_json = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"错误：JSON解析失败 - {e}")
        return None
    
    # 转换为Markdown表格（单表）
    md_output = enum_json_to_md_table(enum_json)
    
    # 写入txt文件（单表）
    with open(txt_output_path, 'w', encoding='utf-8') as f:
        f.write(md_output)
    
    # 转换为按field分组的Markdown表格
    md_by_field = enum_json_to_md_by_field(enum_json)
    
    # 写入txt文件（按field分组）
    with open(txt_by_field_path, 'w', encoding='utf-8') as f:
        f.write(md_by_field)
    
    # 写入Excel文件（按field分Sheet）
    enum_json_to_excel_by_field(enum_json, excel_output_path)
    
    print(f"转换完成！")
    print(f"输入文件：{input_path}")
    print(f"输出TXT（单表）：{txt_output_path}")
    print(f"输出TXT（按字段分组）：{txt_by_field_path}")
    print(f"输出Excel（按字段分Sheet）：{excel_output_path}")
    return txt_output_path, txt_by_field_path, excel_output_path


def batch_process(input_dir="data", output_dir="output", file_extension=".json"):
    """
    批量处理data目录下的所有JSON文件
    
    Args:
        input_dir: 输入目录
        output_dir: 输出目录
        file_extension: 文件扩展名过滤
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, input_dir)
    output_path = os.path.join(script_dir, output_dir)
    
    # 确保输出目录存在
    os.makedirs(output_path, exist_ok=True)
    
    # 获取所有符合条件的文件
    files = [f for f in os.listdir(input_path) if f.endswith(file_extension)]
    
    if not files:
        print(f"提示：在 {input_dir} 目录下未找到 {file_extension} 文件")
        return
    
    print(f"找到 {len(files)} 个文件，开始批量转换...")
    print("-" * 60)
    
    success_count = 0
    for filename in files:
        try:
            print(f"正在处理：{filename}")
            process_enum_file(filename, input_dir, output_dir)
            success_count += 1
            print()
        except Exception as e:
            print(f"处理失败：{filename} - {e}")
            print()
    
    print("=" * 60)
    print(f"批量转换完成！成功：{success_count}/{len(files)}")


if __name__ == "__main__":
    # 方式1：处理单个文件
    # process_enum_file("enum_input.json")
    
    # 方式2：批量处理 data 目录下所有 JSON 文件
    batch_process()
    
    # 方式3：批量处理指定扩展名的文件
    # batch_process(file_extension=".txt")