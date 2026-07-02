"""
Agent主入口

基于Agno的智能Agent实现
整合会话管理、历史记录、多模型策略、业务工具
"""

import os
import base64
import json
import re
from typing import Any
import logging

# 初始化日志
logger = logging.getLogger("agent")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============= 简化的编解码函数（不依赖Agent） =============

def _decode_base64_text(text: str) -> str:
    """解码单个 Base64 文本内容"""
    cleaned = "".join(text.split())
    if not cleaned:
        return ""
    
    # 验证是否为有效的 Base64 字符
    import re
    if not re.match(r'^[A-Za-z0-9+/=\s]+$', cleaned):
        raise ValueError("输入包含非Base64字符，可能是原始文本而非Base64编码")
    
    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)
    
    # 使用 ascii 编码确保兼容性
    decoded_bytes = base64.b64decode(cleaned.encode('ascii'))
    return decoded_bytes.decode("utf-8", errors="replace")


def _extract_normalize_indexes(text: str) -> list:
    """从解码后的文本中提取 normalize 下所有的 index 值"""
    indexes: list = []
    
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


def _extract_indexes_from_obj(obj: Any) -> list:
    """递归提取对象中的 index 字段"""
    indexes: list = []
    
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


def simple_decode(b64_text: str) -> dict:
    """
    解码函数：Try-Decode + JSON 验证策略

    不再使用启发式规则猜测是否为 Base64，而是直接尝试解码。
    解码成功且结果为合法 JSON → 确认为 Base64
    解码失败或结果非 JSON → 按纯文本处理

    优势：
    - 零启发式规则，无误判
    - 天然处理带尾随换行/空白的 Base64（_decode_base64_text 内部 strip）
    - 纯文本 syslog（含 ||、中文等）会直接解码失败，正确回退

    Args:
        b64_text: Base64 编码的文本 或 纯文本

    Returns:
        dict: {
            "status": "success" | "error",
            "decoded_json": dict,
            "decoded_text": str,
            "fields": list,
            "original_log": list,
            "field_count": int
        }
    """
    try:
        cleaned = b64_text.strip()
        if not cleaned:
            return {"status": "error", "error_message": "输入为空"}

        decoded_text: str
        # Try-Decode 策略：先尝试 Base64 解码，再验证结果是否为有效 JSON
        try:
            candidate = _decode_base64_text(cleaned)
            json.loads(candidate)  # 必须可解析为 JSON 才接受为 Base64
            decoded_text = candidate
            logger.info("[DECODE] Base64 解码成功，输出为有效 JSON")
        except (ValueError, json.JSONDecodeError, Exception):
            logger.info("[DECODE] 非 Base64 或解码结果非 JSON，按纯文本处理")
            decoded_text = cleaned

        fields = _extract_normalize_indexes(decoded_text)
        original_log = _extract_original_log_result(decoded_text)

        try:
            decoded_json = json.loads(decoded_text)
        except json.JSONDecodeError:
            decoded_json = {"raw_text": decoded_text[:1000]}

        # 纯文本（非 JSON）兜底：将每行内容保存为 original_log，
        # 让枚举提取等流程可以从上传的 TXT/日志文件中读取原始数据
        if original_log is None and decoded_text and isinstance(decoded_text, str):
            import re as _re_log
            # 跳过仅含空白/分隔线的空行
            raw_lines = [
                line for line in decoded_text.splitlines()
                if line.strip() and not _re_log.match(r'^[=\-_#*]{3,}$', line.strip())
            ]
            if raw_lines:
                original_log = raw_lines[:5000]  # 最多保留 5000 行，避免内存过大
                logger.info(f"[DECODE] 纯文本场景：保存 {len(original_log)} 行为 original_log")

        return {
            "status": "success",
            "decoded_json": decoded_json,
            "decoded_text": decoded_text,
            "fields": fields,
            "original_log": original_log,
            "field_count": len(fields) if fields else 0
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e)
        }


def simple_encode(data: dict) -> dict:
    """
    简化的编码函数，不依赖 Agent
    
    Args:
        data: JSON对象
    
    Returns:
        dict: 编码结果
    """
    try:
        json_text = json.dumps(data, ensure_ascii=False)
        encoded = base64.b64encode(json_text.encode('utf-8')).decode('utf-8')
        
        return {
            "status": "success",
            "encoded": encoded
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e)
        }
