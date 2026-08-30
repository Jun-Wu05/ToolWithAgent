"""
文件上传处理业务逻辑（从 chainlit_app.py 提取）

本模块仅包含纯数据处理函数，不包含任何 Chainlit UI 调用（cl.Message 等）。
所有 UI 渲染保留在 chainlit_app.py 中。
"""

from typing import Any

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


def get_element_file_name(element) -> str:
    """获取上传文件的原始文件名

    Args:
        element: Chainlit 文件元素

    Returns:
        str: 文件名，无法获取时返回 'uploaded_file'
    """
    return getattr(element, 'name', '') or 'uploaded_file'
