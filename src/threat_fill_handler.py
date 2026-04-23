"""
威胁类型填充处理器

提供威胁类型映射的填充功能：
1. 在 normalize 数组中查找匹配的项
2. 将 mapping 表格添加到 matched_item 的 mappings 字段
3. 导出 Base64 编码的结果
"""

import json
import base64
from typing import Tuple, List, Dict, Optional

from src.logger import get_logger

logger = get_logger("threat_fill_handler")


def find_normalize_item(decoded_data: dict, target_field: str) -> Tuple[Optional[dict], List[str]]:
    """
    在 decoded_data 的 normalize 数组中查找匹配的项
    
    Args:
        decoded_data: 解码后的 JSON 对象
        target_field: 用户输入的目标字段名（如 "original_log"）
    
    Returns:
        tuple: (matched_item, available_fields)
               - matched_item: 找到的 normalize 项，未找到则为 None
               - available_fields: 所有可用的 index 值列表
    """
    # 1. 处理 decoded_data 可能是列表的情况（取第一个元素）
    if isinstance(decoded_data, list):
        if decoded_data:
            decoded_data = decoded_data[0]
        else:
            return None, []
    
    if not isinstance(decoded_data, dict):
        return None, []
    
    # 2. 获取 normalize 数组
    normalize = decoded_data.get("normalize", [])
    
    if not normalize:
        logger.warning("[find_normalize_item] normalize 数组为空或不存在")
        return None, []
    
    # 3. 收集所有可用的 index 值
    available_fields = []
    for item in normalize:
        if isinstance(item, dict):
            index_value = item.get("index", "")
            if index_value:
                available_fields.append(index_value)
    
    logger.info(f"[find_normalize_item] 可用的 index 列表: {available_fields}")
    
    # 4. 查找匹配的项（去除引号后比较）
    matched_item = None
    target_clean = target_field.strip('"\'')
    
    for item in normalize:
        if not isinstance(item, dict):
            continue
        
        index_value = item.get("index", "").strip('"\'')
        
        if index_value == target_clean:
            matched_item = item
            logger.info(f"[find_normalize_item] 找到匹配项: index={index_value}")
            break
    
    if not matched_item:
        logger.warning(f"[find_normalize_item] 未找到匹配项: target_field={target_field}")
    
    return matched_item, available_fields


def apply_threat_mapping(decoded_data: dict, mapping_table: list, target_field: str) -> dict:
    """
    将 mapping 表格添加到 normalize 项的 mappings 字段中
    
    Args:
        decoded_data: 解码后的 JSON 对象
        mapping_table: 映射表格列表
                       格式: [{"mappingType": "...", "orgValue": "...", "mappingValue": "..."}]
        target_field: 目标字段名
    
    Returns:
        dict: 更新后的 JSON 对象
        
    Raises:
        ValueError: 找不到匹配的 normalize 项
    """
    # 1. 深拷贝避免修改原数据
    result = json.loads(json.dumps(decoded_data))
    
    logger.info(f"[apply_threat_mapping] 开始应用映射，target_field={target_field}, mapping_count={len(mapping_table)}")
    
    # 2. 查找匹配的 normalize 项
    matched_item, available_fields = find_normalize_item(result, target_field)
    
    if not matched_item:
        available_str = ", ".join(available_fields[:20]) if available_fields else "无"
        raise ValueError(
            f"未找到匹配的 normalize 项！\n"
            f"您输入的字段：{target_field}\n"
            f"可用的字段列表：{available_str}\n\n"
            f"请从上述列表中选择正确的字段名。"
        )
    
    # 3. 初始化 mappings 字段（如果不存在）
    if "mappings" not in matched_item:
        matched_item["mappings"] = []
        logger.info(f"[apply_threat_mapping] 初始化 mappings 字段")
    
    # 4. 添加 mapping 到 mappings 字段（去重）
    mappings_added = 0
    for mapping in mapping_table:
        # 检查是否已存在相同的 orgValue
        exists = any(
            m.get("orgValue") == mapping.get("orgValue")
            for m in matched_item["mappings"]
        )
        
        if not exists:
            matched_item["mappings"].append(mapping)
            mappings_added += 1
            logger.info(
                f"[apply_threat_mapping] 添加映射: "
                f"mappingType={mapping.get('mappingType')}, "
                f"orgValue={mapping.get('orgValue')}, "
                f"mappingValue={mapping.get('mappingValue')}"
            )
        else:
            logger.info(f"[apply_threat_mapping] 跳过已存在的映射: orgValue={mapping.get('orgValue')}")
    
    logger.info(
        f"[apply_threat_mapping] 完成！共添加 {mappings_added} 条映射到 "
        f"normalize 项 (index={matched_item.get('index')}, field={matched_item.get('field')})"
    )
    
    return result


def export_to_base64(data: dict) -> str:
    """
    将 JSON 对象编码为 Base64 字符串
    
    Args:
        data: JSON 对象
    
    Returns:
        str: Base64 编码字符串
    """
    # 1. 序列化 JSON
    json_str = json.dumps(data, ensure_ascii=False)
    logger.info(f"[export_to_base64] JSON 序列化完成，长度: {len(json_str)}")
    
    # 2. Base64 编码
    base64_bytes = base64.b64encode(json_str.encode('utf-8'))
    base64_str = base64_bytes.decode('utf-8')
    
    logger.info(f"[export_to_base64] Base64 编码完成，长度: {len(base64_str)}")
    
    return base64_str


def apply_threat_mapping_with_base64(base64_content: str, mapping_table: list, target_field: str) -> str:
    """
    从 Base64 字符串解析、应用映射、并返回 Base64 结果的便捷函数
    
    Args:
        base64_content: Base64 编码的字符串
        mapping_table: 映射表格列表
        target_field: 目标字段名
    
    Returns:
        str: 填充后的 Base64 字符串
        
    Raises:
        ValueError: 解析或应用失败
    """
    # 1. 解析 Base64
    try:
        json_bytes = base64.b64decode(base64_content)
        decoded_data = json.loads(json_bytes.decode('utf-8'))
        logger.info(f"[apply_threat_mapping_with_base64] Base64 解析成功")
    except Exception as e:
        logger.error(f"[apply_threat_mapping_with_base64] Base64 解析失败: {e}")
        raise ValueError(f"Base64 解析失败: {str(e)}")
    
    # 2. 应用映射
    updated_data = apply_threat_mapping(decoded_data, mapping_table, target_field)
    
    # 3. 导出 Base64
    return export_to_base64(updated_data)