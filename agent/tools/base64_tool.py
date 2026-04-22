"""
Base64 解码 + 字段提取工具

复用 auto/phase1/index.py 的核心逻辑
"""
import base64
import json
import re
from typing import Any


def decode_base64_text(text: str) -> str:
    """解码单个 Base64 文本内容"""
    cleaned = "".join(text.split())
    if not cleaned:
        return ""

    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)

    decoded_bytes = base64.b64decode(cleaned)
    return decoded_bytes.decode("utf-8", errors="replace")


def extract_normalize_indexes(text: str) -> list[Any]:
    """从解码后的文本中提取 normalize 下所有的 index 值"""
    indexes: list[Any] = []

    try:
        payload = json.loads(text)
        indexes.extend(_extract_indexes_from_obj(payload))
        return indexes
    except Exception:
        pass

    pattern = re.compile(r'"normalize"\s*:\s*\[(.*?)\]', re.S)
    match = pattern.search(text)
    if not match:
        return indexes

    block = match.group(1)
    for item in re.finditer(r'"index"\s*:\s*(\[[^\]]*\]|\d+|".*?"|null|true|false)', block, re.S):
        value = item.group(1).strip()
        try:
            indexes.append(json.loads(value))
        except Exception:
            indexes.append(value)

    return indexes


def _extract_indexes_from_obj(obj: Any) -> list[Any]:
    """递归提取对象中的 index 字段"""
    indexes: list[Any] = []

    if isinstance(obj, dict):
        if "normalize" in obj and isinstance(obj["normalize"], list):
            for item in obj["normalize"]:
                if isinstance(item, dict) and "index" in item:
                    indexes.append(item["index"])
        for value in obj.values():
            indexes.extend(_extract_indexes_from_obj(value))
    elif isinstance(obj, list):
        for item in obj:
            indexes.extend(_extract_indexes_from_obj(item))

    return indexes


def extract_original_log_result(text: str) -> Any:
    """
    找到整个对象中 index == "original_log" 的项，直接返回它的 result 数组
    """
    try:
        payload = json.loads(text)
        return _find_original_log_result(payload)
    except Exception as e:
        return None


def _find_original_log_result(obj: Any) -> Any:
    """递归查找 index: "original_log" 并返回对应的 result"""
    if isinstance(obj, dict):
        if obj.get("index") == "original_log" and "result" in obj:
            return obj["result"]
        
        for value in obj.values():
            res = _find_original_log_result(value)
            if res is not None:
                return res

    elif isinstance(obj, list):
        for item in obj:
            res = _find_original_log_result(item)
            if res is not None:
                return res
    return None


def base64_decode_and_extract(b64_text: str) -> dict:
    """
    Agno Tool: 解码 Base64 文本并提取字段信息
    
    Args:
        b64_text: Base64 编码的文本内容
        
    Returns:
        dict: 包含解码结果和提取字段的字典
            - decoded_json: 解码后的 JSON 对象
            - decoded_text: 解码后的文本
            - fields: 提取的 normalize indexes 数组
            - original_log: original_log 对应的 result
            - status: "success" 或 "error"
            - error_message: 如果失败，错误信息
    """
    from agno.tools import tool
    
    try:
        # 清理空白字符
        cleaned = "".join(b64_text.split())
        
        if not cleaned:
            return {
                "status": "error",
                "error_message": "输入为空"
            }
        
        # 补齐 padding
        missing_padding = len(cleaned) % 4
        if missing_padding:
            cleaned += "=" * (4 - missing_padding)
        
        # 解码
        decoded_bytes = base64.b64decode(cleaned)
        decoded_text = decoded_bytes.decode("utf-8", errors="replace")
        
        # 提取字段
        fields = extract_normalize_indexes(decoded_text)
        original_log = extract_original_log_result(decoded_text)
        
        # 尝试解析 JSON
        try:
            decoded_json = json.loads(decoded_text)
        except json.JSONDecodeError:
            decoded_json = {"raw_text": decoded_text[:1000]}
        
        return {
            "status": "success",
            "decoded_json": decoded_json,
            "decoded_text": decoded_text,
            "fields": fields,
            "original_log": original_log,
            "field_count": len(fields) if fields else 0
        }
        
    except binascii.Error as e:
        return {
            "status": "error",
            "error_message": f"Base64 解码失败: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"处理失败: {str(e)}"
        }
