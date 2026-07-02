"""
JSON 解析器和数据处理工具

提供通用的 JSON 解析和表格创建功能，供 Chainlit UI 层调用
"""

import json
import re
from agent.shared.logger import get_logger

logger = get_logger("parsers")


# 拒绝响应检测模式：LLM 索要数据、请求额外输入时的关键词
_REFUSAL_PATTERNS = [
    r"(?:请|需要|提供)(?:你|您|给我|输入)?.{0,10}(?:原始日志|日志样本|解码.{0,5}日志|更多数据|文件内容)",
    r"(?:无法|不能|不可以|没有足够).{0,10}(?:处理|映射|分析|完成|进行)",
    r"(?:需要先|必须先|必须).{0,15}(?:解码|查看|读取|获得)(?:原.{0,5}日志|样本|数据)",
    r"(?:缺少|缺失|不足).{0,10}(?:日志|样本|数据|内容|字段)",
    r"(?:请先|建议先).{0,15}(?:上传|提交|输入|补充)", 
]


def _is_refusal_response(content: str) -> bool:
    """检测 LLM 响应是否为拒绝对话（索要数据/无法处理等非JSON回复）"""
    content_lower = content.strip()
    for pattern in _REFUSAL_PATTERNS:
        if re.search(pattern, content_lower):
            return True
    return False


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
            else:
                return False
        # 值逻辑校验：系统属性名称 == "未匹配" 时，匹配状态必须也是"未匹配"
        if item.get("系统属性名称") == "未匹配" and item.get("匹配状态") != "未匹配":
            logger.warning(f"[PARSER] 自动修正矛盾数据(未匹配状态不一致): {item}")
            item["匹配状态"] = "未匹配"
        return True
    
    # 记录原始内容（完整输出）- 移到 Pydantic 处理之前，确保所有情况都能记录
    logger.info(f"[PARSER] 收到内容:\n{content}")
    
    # CHANGED: 优先处理 Pydantic 对象（output_schema 模式）
    items = _extract_items_from_pydantic(content, "PARSER")
    if items:
        valid_result = [item for item in items if validate_item(item)]
        if valid_result:
            logger.info(f"[PARSER] Pydantic 对象解析成功，获得 {len(valid_result)} 条有效记录")
            return valid_result
    
    content_stripped = str(content).strip()  # CHANGED: 使用 str() 确保是字符串
    
    # 方法1：去除前后空白后直接尝试解析
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
    
    # 方法4：尝试替换中文引号/括号后重试 JSON 解析
    fixed_content = content_stripped
    fixed_content = fixed_content.replace('\u201c', '"').replace('\u201d', '"')  # 中文双引号
    fixed_content = fixed_content.replace('\u2018', "'").replace('\u2019', "'")  # 中文单引号
    fixed_content = fixed_content.replace('\uff08', '(').replace('\uff09', ')')  # 全角括号
    if fixed_content != content_stripped:
        logger.info("[PARSER] 方法4：修复中文标点后重试")
        try:
            result = json.loads(fixed_content)
            if isinstance(result, list):
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info(f"[PARSER] 方法4解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError:
            pass
    
    # 方法5：JSON 修复 — 使用 regex 逐项提取，容忍部分损坏
    item_pattern = r'\{\s*"原始字段名"\s*:\s*"([^"]*)"\s*,\s*"系统属性名称"\s*:\s*"([^"]*)"\s*,\s*"匹配状态"\s*:\s*"([^"]*)"\s*\}'
    items = re.findall(item_pattern, content_stripped)
    if items:
        logger.info(f"[PARSER] 方法5（regex逐项提取）成功，获得 {len(items)} 条记录")
        result = [
            {"原始字段名": raw, "系统属性名称": std, "匹配状态": status}
            for raw, std, status in items
        ]
        valid_result = [item for item in result if validate_item(item)]
        if valid_result:
            return valid_result
    
    # 所有 JSON 解析方法均失败后，才检查是否为拒绝响应（用于日志区分原因）
    if _is_refusal_response(content_stripped):
        logger.warning("[PARSER] 所有 JSON 解析均失败，且内容疑似拒绝响应（索要数据/无法处理），建议重试")
    else:
        logger.warning(f"[PARSER] 所有方法均解析失败，无法提取有效的映射结果")
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
    
    # 记录原始内容（完整输出）
    logger.info(f"[THREAT_PARSER] 收到内容:\n{content}")
    
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