"""Application 文件输入：确定性解码 Base64、JSON 与纯文本上传内容。"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from application.session_state import PrimaryDatasetSnapshot


logger = logging.getLogger("agent")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _decode_base64_text(text: str) -> str:
    """解码单个 Base64 文本内容。"""
    cleaned = "".join(text.split())
    if not cleaned:
        return ""

    if not re.match(r"^[A-Za-z0-9+/=\s]+$", cleaned):
        raise ValueError("输入包含非Base64字符，可能是原始文本而非Base64编码")

    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)

    decoded_bytes = base64.b64decode(cleaned.encode("ascii"))
    return decoded_bytes.decode("utf-8", errors="replace")


def _extract_normalize_indexes(text: str) -> list:
    """从解码后的文本中提取 normalize 下所有的 index 值。"""
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
    for item in re.finditer(
        r'"index"\s*:\s*(\[[^\]]*\]|\d+|".*?"|null|true|false)', block, re.S
    ):
        value = item.group(1).strip()
        try:
            indexes.append(json.loads(value))
        except Exception:
            indexes.append(value)

    return indexes


def _extract_indexes_from_obj(obj: Any) -> list:
    """递归提取对象中的 index 字段。"""
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
    """找到整个对象中 index == original_log 的项并返回 result。"""
    try:
        payload = json.loads(text)
        return _find_original_log_result(payload)
    except Exception:
        return None


def _find_original_log_result(obj: Any) -> Any:
    """递归查找 index 为 original_log 的 result。"""
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
    """以 Try-Decode + JSON 验证策略解析上传文本。

    解码成功且结果为合法 JSON 时接受 Base64；否则按原始纯文本处理。
    返回结构、错误消息和纯文本 5000 行限制属于上传链路的兼容契约。
    """
    try:
        cleaned = b64_text.strip()
        if not cleaned:
            return {"status": "error", "error_message": "输入为空"}

        decoded_text: str
        try:
            candidate = _decode_base64_text(cleaned)
            json.loads(candidate)
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

        if original_log is None and decoded_text and isinstance(decoded_text, str):
            raw_lines = [
                line
                for line in decoded_text.splitlines()
                if line.strip() and not re.match(r"^[=\-_#*]{3,}$", line.strip())
            ]
            if raw_lines:
                original_log = raw_lines[:5000]
                logger.info(
                    "[DECODE] 纯文本场景：保存 %s 行为 original_log",
                    len(original_log),
                )

        return {
            "status": "success",
            "decoded_json": decoded_json,
            "decoded_text": decoded_text,
            "fields": fields,
            "original_log": original_log,
            "field_count": len(fields) if fields else 0,
        }
    except Exception as error:
        return {"status": "error", "error_message": str(error)}


def build_simplified_data(decode_result: dict[str, Any]) -> dict[str, Any]:
    """从解码结果构建供模型输入使用的精简数据。"""
    indexes = decode_result.get("fields", [])
    original_log = decode_result.get("original_log", [])

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

    return {"fields": indexes, "original_log_sample": original_log_sample}


_PRIMARY_DATASET_STATE_KEYS = (
    "decoded_data",
    "decoded_fields",
    "original_log",
    "simplified_data",
    "decoded_text",
    "raw_log_lines",
    "uploaded_file_name",
    "uploaded_file_time",
    "raw_base64",
    "enum_excel_path",
    "enum_preview",
    "enum_mapping_sheets",
    "enum_fill_contributions",
    "stale_enum_config_refs",
    "enum_pending_refills",
    "last_mapping_data",
    "excel_data",
    "excel_filename",
    "last_threat_data",
    "last_enum_extract_result",
    "latest_threat_artifact",
    "latest_enum_artifact",
    "log_classification",
    "log_knowledge_submission",
    "rule_source_fields",
    "pending_rule_source_step",
    "pending_plan",
    "threat_source_field_override",
    "current_execution",
    "previous_execution",
    "mapped_sub_rules",
    "sub_rule_mapping_results",
    "conversation_history",
)


def commit_primary_dataset(
    session: Any, snapshot: PrimaryDatasetSnapshot
) -> None:
    """将已完整解析和校验的主数据快照原子提交到会话。"""
    replace = getattr(session, "replace_primary_dataset", None)
    if callable(replace):
        replace(snapshot)
        return
    staged_values = {
        "decoded_data": snapshot.decoded_data,
        "decoded_fields": list(snapshot.decoded_fields),
        "original_log": snapshot.original_log,
        "simplified_data": snapshot.simplified_data,
        "decoded_text": snapshot.decoded_text,
        "raw_log_lines": snapshot.raw_log_lines,
        "raw_base64": snapshot.raw_base64,
        "uploaded_file_name": snapshot.uploaded_file_name,
        "uploaded_file_time": snapshot.uploaded_file_time,
        "conversation_history": [],
    }
    for key in _PRIMARY_DATASET_STATE_KEYS:
        session.pop(key, None)
    session.update(staged_values)


__all__ = ["build_simplified_data", "commit_primary_dataset", "simple_decode"]
