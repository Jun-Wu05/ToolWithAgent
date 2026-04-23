"""
JSON 解析器和数据处理工具

提供通用的 JSON 解析和表格创建功能，供 Chainlit UI 层调用
"""

import json
import re
from src.logger import get_logger

logger = get_logger("parsers")


def parse_json_mapping_result(content: str) -> list:
    """
    解析Agent返回的JSON映射结果
    只提取正确的3列格式：原始字段名、系统属性名称、匹配状态
    
    Args:
        content: Agent返回的内容（可能是纯JSON或包含在其他文本中）
    
    Returns:
        list: 映射结果列表，解析失败返回空列表
    """
    # 定义正确的列名
    VALID_COLUMNS = {"原始字段名", "系统属性名称", "匹配状态"}
    
    def validate_item(item: dict) -> bool:
        """验证单条记录是否符合格式要求"""
        if not isinstance(item, dict):
            return False
        # 检查是否只有3个键
        keys = set(item.keys())
        if keys != VALID_COLUMNS:
            # 过滤多余列，只保留需要的
            filtered = {k: v for k, v in item.items() if k in VALID_COLUMNS}
            if len(filtered) == 3:
                item.clear()
                item.update(filtered)
                return True
            return False
        return True
    
    # 记录原始内容（完整输出）
    logger.info(f"[PARSER] 收到内容:\n{content}")
    
    # 方法1：去除前后空白后直接尝试解析
    content_stripped = content.strip()
    try:
        result = json.loads(content_stripped)
        if isinstance(result, list):
            valid_result = [item for item in result if validate_item(item)]
            if valid_result:
                logger.info(f"[PARSER] 方法1解析成功，获得 {len(valid_result)} 条有效记录")
                return valid_result
    except json.JSONDecodeError:
        pass
    
    # 方法2：查找第一个 [ 到最后一个 ] 之间的内容
    first_bracket = content_stripped.find('[')
    last_bracket = content_stripped.rfind(']')
    
    if first_bracket != -1 and last_bracket > first_bracket:
        json_candidate = content_stripped[first_bracket:last_bracket + 1]
        logger.info(f"[PARSER] 方法2找到JSON候选，长度: {len(json_candidate)}")
        try:
            result = json.loads(json_candidate)
            if isinstance(result, list) and len(result) > 0:
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info(f"[PARSER] 方法2解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError as e:
            logger.warning(f"[PARSER] 方法2 JSON解析失败: {e}")
            pass
    
    # 方法3：尝试提取代码块中的JSON
    code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
    matches = re.findall(code_block_pattern, content_stripped)
    logger.info(f"[PARSER] 方法3找到 {len(matches)} 个代码块")
    for match in matches:
        try:
            result = json.loads(match.strip())
            if isinstance(result, list):
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info(f"[PARSER] 方法3解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError:
            continue
    
    logger.warning(f"[PARSER] 解析失败，无法提取有效的映射结果")
    return []


def parse_json_threat_result(content: str) -> list:
    """
    解析威胁类型映射结果
    只提取3列格式：mappingType, orgValue, mappingValue
    
    Args:
        content: Agent返回的内容
    
    Returns:
        list: 映射结果列表，解析失败返回空列表
    """
    # 威胁类型只有3列
    VALID_COLUMNS = {"mappingType", "orgValue", "mappingValue"}
    
    def validate_item(item: dict) -> bool:
        """验证单条记录是否符合格式要求"""
        if not isinstance(item, dict):
            return False
        keys = set(item.keys())
        if keys != VALID_COLUMNS:
            # 过滤多余列，只保留需要的
            filtered = {k: v for k, v in item.items() if k in VALID_COLUMNS}
            if len(filtered) == 3:
                item.clear()
                item.update(filtered)
                return True
            return False
        return True
    
    # 记录原始内容（完整输出）
    logger.info(f"[THREAT_PARSER] 收到内容:\n{content}")
    
    # 方法1：去除前后空白后直接尝试解析
    content_stripped = content.strip()
    try:
        result = json.loads(content_stripped)
        if isinstance(result, list):
            valid_result = [item for item in result if validate_item(item)]
            if valid_result:
                logger.info(f"[THREAT_PARSER] 方法1解析成功，获得 {len(valid_result)} 条有效记录")
                return valid_result
    except json.JSONDecodeError:
        pass
    
    # 方法2：查找第一个 [ 到最后一个 ] 之间的内容
    # 这是最宽松的匹配，处理 LLM 输出带有前缀文字的情况
    first_bracket = content_stripped.find('[')
    last_bracket = content_stripped.rfind(']')
    
    if first_bracket != -1 and last_bracket > first_bracket:
        json_candidate = content_stripped[first_bracket:last_bracket + 1]
        logger.info(f"[THREAT_PARSER] 方法2找到JSON候选，长度: {len(json_candidate)}")
        try:
            result = json.loads(json_candidate)
            if isinstance(result, list) and len(result) > 0:
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info(f"[THREAT_PARSER] 方法2解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError as e:
            logger.warning(f"[THREAT_PARSER] 方法2 JSON解析失败: {e}")
            pass
    
    # 方法3：尝试提取代码块中的JSON
    code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
    matches = re.findall(code_block_pattern, content_stripped)
    logger.info(f"[THREAT_PARSER] 方法3找到 {len(matches)} 个代码块")
    for match in matches:
        try:
            result = json.loads(match.strip())
            if isinstance(result, list):
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info(f"[THREAT_PARSER] 方法3解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError:
            continue
    
    logger.warning(f"[THREAT_PARSER] 解析失败，无法提取有效的威胁映射结果")
    return []


def create_dataframe_elements(mapping_data: list) -> list:
    """
    根据映射数据创建 Chainlit Dataframe 元素
    
    Args:
        mapping_data: 映射结果列表
    
    Returns:
        list: Chainlit 元素列表
    """
    import pandas as pd
    
    if not mapping_data:
        return []
    
    # 将列表转换为 pandas.DataFrame
    df = pd.DataFrame(mapping_data)
    
    # 使用 cl.Dataframe 展示数据
    # pagination=0 禁用分页，一次性展示所有行
    import chainlit as cl
    elements = [
        cl.Dataframe(
            data=df,
            display="inline",
            title="📊 映射结果",
            pagination=0,  # 设为0禁用分页
        )
    ]
    
    return elements