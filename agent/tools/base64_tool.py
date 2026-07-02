"""
Base64 解码 + 字段提取工具

Agno Tool版本
"""
import base64
import json
import re
from typing import Any, Optional

from agno.tools import tool


def _decode_base64_text(text: str) -> str:
    """解码单个 Base64 文本内容"""
    cleaned = "".join(text.split())
    if not cleaned:
        return ""
    
    # 验证是否为有效的 Base64 字符
    if not re.match(r'^[A-Za-z0-9+/=\s]+$', cleaned):
        raise ValueError("输入包含非Base64字符，可能是原始文本而非Base64编码")

    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)

    # 使用 ascii 编码确保兼容性
    decoded_bytes = base64.b64decode(cleaned.encode('ascii'))
    return decoded_bytes.decode("utf-8", errors="replace")


def _extract_normalize_indexes(text: str) -> list[Any]:
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


def _extract_original_log_result(text: str) -> Any:
    """找到整个对象中 index == "original_log" 的项，直接返回它的 result 数组"""
    try:
        payload = json.loads(text)
        return _find_original_log_result(payload)
    except Exception:
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


@tool(name="base64_decode", description="解码Base64文本并提取字段信息")
def base64_decode_tool(b64_text: str) -> str:
    """
    解码 Base64 文本并提取字段信息
    
    当用户提供 Base64 编码的数据时使用此工具：
    1. 接收 Base64 文本
    2. 解码为原始文本
    3. 提取 normalize indexes
    4. 提取 original_log result
    5. 返回解码结果和提取的字段
    
    Args:
        b64_text: Base64 编码的文本内容
    
    Returns:
        解码结果，包含字段信息和JSON对象
    """
    try:
        # 清理空白字符
        cleaned = "".join(b64_text.split())
        
        if not cleaned:
            return json.dumps({
                "status": "error",
                "error_message": "输入为空"
            }, ensure_ascii=False)
        
        # 补齐 padding
        missing_padding = len(cleaned) % 4
        if missing_padding:
            cleaned += "=" * (4 - missing_padding)
        
        # 解码
        decoded_bytes = base64.b64decode(cleaned)
        decoded_text = decoded_bytes.decode("utf-8", errors="replace")
        
        # 提取字段
        fields = _extract_normalize_indexes(decoded_text)
        original_log = _extract_original_log_result(decoded_text)
        
        # 尝试解析 JSON
        try:
            decoded_json = json.loads(decoded_text)
        except json.JSONDecodeError:
            decoded_json = {"raw_text": decoded_text[:1000]}
        
        result = {
            "status": "success",
            "decoded_json": decoded_json,
            "decoded_text": decoded_text[:500] + "..." if len(decoded_text) > 500 else decoded_text,
            "fields": fields,
            "original_log": original_log,
            "field_count": len(fields) if fields else 0,
            "message": f"成功解码，提取到 {len(fields) if fields else 0} 个字段"
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error_message": f"Base64 解码失败: {str(e)}"
        }, ensure_ascii=False)


@tool(name="base64_encode", description="将JSON对象编码为Base64")
def base64_encode_tool(json_data: Any) -> str:
    """
    将 JSON 对象编码为 Base64
    
    在处理完成后，使用此工具将结果编码为 Base64：
    1. 接收 JSON 对象或文本
    2. 编码为 Base64
    3. 返回 Base64 文本
    
    Args:
        json_data: JSON 对象或文本
    
    Returns:
        Base64 编码的文本
    """
    try:
        # 如果是字符串，先尝试解析为 JSON
        if isinstance(json_data, str):
            try:
                json_obj = json.loads(json_data)
            except json.JSONDecodeError:
                json_obj = json_data
        else:
            json_obj = json_data
        
        # 序列化为 JSON 字符串
        json_text = json.dumps(json_obj, ensure_ascii=False)
        
        # 编码为 Base64
        encoded = base64.b64encode(json_text.encode('utf-8')).decode('utf-8')
        
        return encoded
        
    except Exception as e:
        return f"编码失败: {str(e)}"
