"""
枚举映射表的 Excel 读取与展平。

历史说明：本模块曾提供 Agno Tool 版枚举工具（enum_field_tool /
apply_enum_mapping_tool / apply_enum_fill / apply_enum_with_base64 及配套
私有函数）；生产枚举链路已改走 agent/shared/mapping_utils 的
apply_enum_fill_with_contributions 与 Application 适配器，旧壳已删除
（issue #328）。现仅保留 Excel 枚举映射读取（read_enum_mappings_from_excel）
与展平（flatten_enum_mappings）——web/file_handlers 与
application/enum_mapping_attachments 消费。
"""
import os
from collections import defaultdict
from typing import Dict, List

from openpyxl import load_workbook


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
                mapping_type = str(row[0]).upper() if row[0] is not None else "EQUAL"
                if mapping_type not in valid_types:
                    mapping_type = "EQUAL"

                org_value = str(row[1]).strip() if row[1] is not None else ""
                mapping_value = str(row[2]).strip() if row[2] is not None else ""

                if not org_value:
                    continue

                # 对于 REGULAR 类型，智能添加通配符
                if mapping_type == "REGULAR":
                    # 如果已经以 .* 开头（包括 .* 和 (?i).*），则不添加
                    if org_value.startswith(".*") or org_value.startswith("(?i).*"):
                        # 已经是完整正则，不做任何修改
                        pass
                    else:
                        # 简单文本，添加通配符
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
            else:
                raise ValueError(f"枚举映射 Sheet `{sheet_name}` 没有有效规则")
    finally:
        wb.close()

    return dict(all_mappings)


def flatten_enum_mappings(mappings: Dict[str, List[Dict]]) -> List[Dict]:
    """把按 Sheet 管理的枚举映射展平为兼容现有事实层的预览行。"""
    preview = []
    for field_name, field_mappings in mappings.items():
        for mapping in field_mappings:
            display_org = mapping["orgValue"]
            if display_org.startswith(".*") and display_org.endswith(".*"):
                display_org = display_org[2:-2]
            preview.append(
                {
                    "目标字段": field_name,
                    "mappingType": mapping["mappingType"],
                    "原始值": display_org,
                    "映射值": mapping["mappingValue"],
                }
            )
    return preview
