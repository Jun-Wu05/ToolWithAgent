"""
JSON 解析器和数据处理工具

提供通用的 JSON 解析和表格创建功能，供 Chainlit UI 层调用
"""

import json
import re
from agent.shared.logger import get_logger
from application.parsing import parse_json_mapping_result

logger = get_logger("parsers")


def _extract_items_from_pydantic(content, logger_name: str) -> list:
    """
    从 Pydantic 对象或字典中提取 items 列表（通用函数）
    
    支持三种输入类型：
    1. Pydantic 对象（有 items 属性）
    2. 字典（有 items 键，output_schema 格式）
    3. 列表（已经是数组格式）
    
    Args:
        content: 可能是 Pydantic 对象、字典或列表
        logger_name: 日志前缀（"PARSER" 或 "THREAT_PARSER"）
    
    Returns:
        list: 提取的 items 列表（字典格式），失败返回空列表
    """
    # 检查是否有 items 属性（Pydantic 对象）
    if hasattr(content, 'items') and isinstance(content.items, list):
        logger.info(f"[{logger_name}] 检测到 Pydantic 对象，直接提取 items")
        # 将 Pydantic 对象转换为字典列表
        result = []
        for item in content.items:
            if hasattr(item, 'model_dump'):
                # Pydantic v2
                result.append(item.model_dump())
            elif hasattr(item, 'dict'):
                # Pydantic v1
                result.append(item.dict())
            else:
                # 其他情况，尝试转换为字典
                result.append(dict(item))
        return result
    
    # 如果是字典且有 items 键（output_schema 格式）
    if isinstance(content, dict) and "items" in content and isinstance(content["items"], list):
        logger.info(f"[{logger_name}] 检测到 output_schema 格式，自动解包 items")
        return content["items"]
    
    # 如果是列表（已经是数组格式）
    if isinstance(content, list):
        logger.info(f"[{logger_name}] 检测到列表格式，直接使用")
        return content
    
    return []


def parse_json_threat_result(content: str) -> list:
    """
    解析威胁类型映射结果
    只提取3列格式：mappingType, orgValue, mappingValue

    兼容两种输出格式：
    - output_schema 模式: {"items": [...]}
    - 纯 JSON 数组模式: [...]
    
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
    
    # CHANGED: 优先处理 Pydantic 对象（output_schema 模式）
    items = _extract_items_from_pydantic(content, "THREAT_PARSER")
    if items:
        valid_result = [item for item in items if validate_item(item)]
        if valid_result:
            logger.info(f"[THREAT_PARSER] Pydantic 对象解析成功，获得 {len(valid_result)} 条有效记录")
            return valid_result
    
    # 威胁映射结果同样只记录边界元数据，不记录用户提供的原始枚举值。
    logger.info("[THREAT_PARSER] 收到模型结果: content_type=%s content_length=%s", type(content).__name__, len(str(content)))
    
    # 方法1：去除前后空白后直接尝试解析
    content_stripped = str(content).strip()  # CHANGED: 使用 str() 确保是字符串
    try:
        result = json.loads(content_stripped)
        items = _extract_items_from_pydantic(result, "THREAT_PARSER")  # CHANGED: 使用通用函数
        if items:
            valid_result = [item for item in items if validate_item(item)]
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
            items = _extract_items_from_pydantic(result, "THREAT_PARSER")  # CHANGED: 使用通用函数
            if items:
                valid_result = [item for item in items if validate_item(item)]
                if valid_result:
                    logger.info(f"[THREAT_PARSER] 方法2解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError as e:
            logger.warning(f"[THREAT_PARSER] 方法2 JSON解析失败: {e}")
            pass
    
    # 方法2.5：如果方法2解析失败，但原始内容包含 {"items": [...]}，尝试先解包 items
    # 这处理 output_schema 产生的 {"items": [...]} 被含在额外文本中的场景
    if first_bracket == -1:
        # 用正则直接提取 items 数组内容
        items_pattern = r'"items"\s*:\s*\[([\s\S]*?)\]'
        items_match = re.search(items_pattern, content_stripped)
        if items_match:
            items_candidate = "[" + items_match.group(1) + "]"
            logger.info(f"[THREAT_PARSER] 方法2.5 尝试解析 items 子数组，长度: {len(items_candidate)}")
            try:
                items_result = json.loads(items_candidate)
                if isinstance(items_result, list) and len(items_result) > 0:
                    valid_result = [item for item in items_result if validate_item(item)]
                    if valid_result:
                        logger.info(f"[THREAT_PARSER] 方法2.5 解析成功，获得 {len(valid_result)} 条有效记录")
                        return valid_result
            except json.JSONDecodeError as e:
                logger.warning(f"[THREAT_PARSER] 方法2.5 JSON解析失败: {e}")
                pass
    
    # 方法3：尝试提取代码块中的JSON
    code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
    matches = re.findall(code_block_pattern, content_stripped)
    logger.info(f"[THREAT_PARSER] 方法3找到 {len(matches)} 个代码块")
    for match in matches:
        try:
            result = json.loads(match.strip())
            items = _extract_items_from_pydantic(result, "THREAT_PARSER")  # CHANGED: 使用通用函数
            if items:
                valid_result = [item for item in items if validate_item(item)]
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
