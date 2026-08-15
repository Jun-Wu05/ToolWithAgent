"""
文件上传处理业务逻辑（从 chainlit_app.py 提取）

本模块仅包含纯数据处理函数，不包含任何 Chainlit UI 调用（cl.Message 等）。
所有 UI 渲染保留在 chainlit_app.py 中。
"""

import json
from typing import Any, Dict, List

from agent.shared.logger import get_logger

logger = get_logger("file_handler")


def read_element_content(element) -> str:
    """从上传元素中读取文件内容（兼容多种 element 类型）

    Args:
        element: Chainlit 文件元素（File 或 Element 对象）

    Returns:
        str: 文件文本内容
    """
    if hasattr(element, 'path') and element.path:
        with open(element.path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    elif hasattr(element, 'content'):
        content = element.content
        if isinstance(content, bytes):
            return content.decode('utf-8', errors='ignore')
        return str(content)
    else:
        return str(element)


def decode_file_content(file_content: str) -> Dict[str, Any]:
    """解码 Base64 文件内容

    Args:
        file_content: 原始文件内容字符串

    Returns:
        dict: simple_decode 返回的解码结果
    """
    from agent.core.agent import simple_decode
    return simple_decode(file_content)


def build_simplified_data(decode_result: Dict[str, Any]) -> Dict[str, Any]:
    """从解码结果构建 simplified_data（精简上下文，供 LLM 输入构建使用）

    Args:
        decode_result: simple_decode 返回的结果字典

    Returns:
        dict: 包含 fields 和 original_log_sample 的简化数据
    """
    indexes = decode_result.get("fields", [])
    original_log = decode_result.get("original_log", [])

    # 修复：original_log 可能是 string（JSON字符串）、list 或 dict
    if isinstance(original_log, list):
        first_item = original_log[0] if original_log else ""
        if isinstance(first_item, (dict, list)):
            original_log_sample = json.dumps(first_item, ensure_ascii=False)
        else:
            original_log_sample = str(first_item) if first_item else ""
    elif isinstance(original_log, str):
        original_log_sample = original_log
    elif isinstance(original_log, dict):
        original_log_sample = json.dumps(original_log, ensure_ascii=False)
    else:
        original_log_sample = str(original_log) if original_log else ""

    return {
        "fields": indexes,
        "original_log_sample": original_log_sample
    }


def get_element_file_name(element) -> str:
    """获取上传文件的原始文件名

    Args:
        element: Chainlit 文件元素

    Returns:
        str: 文件名，无法获取时返回 'uploaded_file'
    """
    return getattr(element, 'name', '') or 'uploaded_file'
