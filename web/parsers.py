"""
解析器模块 - Markdown 表格解析
"""
import pandas as pd


def parse_markdown_to_dataframe(markdown_table: str) -> pd.DataFrame:
    """
    解析标准字段的 Markdown 表格
    
    Args:
        markdown_table: Markdown 格式的表格字符串
        
    Returns:
        pd.DataFrame: 包含三列的 DataFrame (原始字段名, 系统属性名称, 匹配状态/说明)
    """
    rows = []
    lines = markdown_table.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or '---' in line:
            continue
        if line.startswith('|'):
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            if len(cells) >= 2:
                while len(cells) < 3:
                    cells.append("")
                rows.append(cells)
    
    if rows:
        return pd.DataFrame(rows, columns=["原始字段名", "系统属性名称", "匹配状态/说明"])
    return pd.DataFrame(columns=["原始字段名", "系统属性名称", "匹配状态/说明"])


def parse_threat_markdown_to_dataframe(markdown_table: str) -> pd.DataFrame:
    """
    解析威胁类型的 Markdown 表格（三列格式：mappingType, orgValue, mappingValue）
    
    Args:
        markdown_table: Markdown 格式的表格字符串
        
    Returns:
        pd.DataFrame: 包含三列的 DataFrame (mappingType, orgValue, mappingValue)
    """
    rows = []
    lines = markdown_table.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or '---' in line:
            continue
        if line.startswith('|'):
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            if len(cells) >= 3:
                # 跳过表头
                if 'mappingType' in cells[0] or 'orgValue' in cells[0]:
                    continue
                # 只取前三列
                mapping_type = cells[0]
                org_value = cells[1]
                mapping_value = cells[2]
                
                if mapping_type == "REGULAR" and org_value and mapping_value:
                    rows.append({
                        "mappingType": mapping_type,
                        "orgValue": org_value,
                        "mappingValue": mapping_value
                    })
    
    if rows:
        df = pd.DataFrame(rows)
        return df
    return None
