"""批量解码 data 目录中的 Base64 文本，并提取 normalize 里的 index 值。"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any


def decode_base64_text(text: str) -> str:
    """解码单个 Base64 文本内容。"""
    cleaned = "".join(text.split())
    if not cleaned:
        return ""

    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)

    decoded_bytes = base64.b64decode(cleaned)
    return decoded_bytes.decode("utf-8", errors="replace")


def extract_normalize_indexes(text: str) -> list[Any]:
    """从解码后的文本中提取 normalize 下所有的 index 值。"""
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
    """递归提取对象中的 index 字段。"""
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
    """
    【正确逻辑】
    找到整个对象中 index == "original_log" 的项，直接返回它的 result 数组
    """
    try:
        payload = json.loads(text)
        result = _find_original_log_result(payload)
        return result if result is not None else ""
    except Exception as e:
        return ""


def _find_original_log_result(obj: Any) -> Any:
    """递归查找 index: "original_log" 并返回对应的 result"""
    if isinstance(obj, dict):
        # 关键匹配：只要有 index = original_log，直接返回 result
        if obj.get("index") == "original_log" and "result" in obj:
            return obj["result"]
        
        # 递归查找所有层级
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


def process_files() -> None:
    """处理 data 目录下所有 txt 文件，并输出到 output 目录。"""
    base_dir = Path(__file__).resolve().parent
    input_dir = base_dir / "data"
    output_dir = base_dir / "output"
    index_output_file = output_dir / "normalize_indexes.txt"
    output_dir.mkdir(parents=True, exist_ok=True)

    all_indexes: list[dict[str, Any]] = []

    for input_file in input_dir.glob("*.txt"):
        raw_text = input_file.read_text(encoding="utf-8", errors="ignore")
        try:
            decoded_text = decode_base64_text(raw_text)
        except Exception as exc:
            decoded_text = f"解码失败：{exc}"

        output_file = output_dir / input_file.name
        output_file.write_text(decoded_text, encoding="utf-8")
        print(f"已处理：{input_file.name} -> {output_file}")

        indexes = extract_normalize_indexes(decoded_text)
        # 提取 original_log 对应的完整 result 值
        original_log_result = _extract_original_log_result(decoded_text)
        if indexes or original_log_result:
            field_values = [str(index_value) for index_value in indexes]
            all_indexes.append({
                "file": input_file.name,
                "original_log_json": original_log_result,  # 现在是正确的 result 值
                "field": field_values,
            })

    # 处理空数据情况，避免索引越界
    output_data = all_indexes[0] if len(all_indexes) == 1 else all_indexes
    index_output_file.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=4),
        encoding="utf-8"
    )
    print(f"已输出 normalize 的 index 汇总：{index_output_file}")


if __name__ == "__main__":
    process_files()