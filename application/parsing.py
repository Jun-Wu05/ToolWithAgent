"""提供与界面无关的确定性 JSON 解析。"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.shared.logger import get_logger


logger = get_logger("parsers")

_MAPPING_REFUSAL_PATTERNS = [
    r"(?:请|需要|提供)(?:你|您|给我|输入)?.{0,10}(?:原始日志|日志样本|解码.{0,5}日志|更多数据|文件内容)",
    r"(?:无法|不能|不可以|没有足够).{0,10}(?:处理|映射|分析|完成|进行)",
    r"(?:需要先|必须先|必须).{0,15}(?:解码|查看|读取|获得)(?:原.{0,5}日志|样本|数据)",
    r"(?:缺少|缺失|不足).{0,10}(?:日志|样本|数据|内容|字段)",
    r"(?:请先|建议先).{0,15}(?:上传|提交|输入|补充)",
]


def parse_json_safe(text: str) -> dict[str, Any] | None:
    """解析 JSON 对象，兼容 Markdown 代码块与正文中的对象片段。"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _is_mapping_refusal_response(content: str) -> bool:
    """检测字段映射模型是否以索要数据等拒绝文本代替结构化结果。"""
    return any(re.search(pattern, content.strip()) for pattern in _MAPPING_REFUSAL_PATTERNS)


def _extract_mapping_items(content: Any) -> list[dict[str, Any]]:
    """从字段映射的 Pydantic、字典或列表结构中提取记录。"""
    if hasattr(content, "items") and isinstance(content.items, list):
        logger.info("[PARSER] 检测到 Pydantic 对象，直接提取 items")
        result = []
        for item in content.items:
            if hasattr(item, "model_dump"):
                result.append(item.model_dump())
            elif hasattr(item, "dict"):
                result.append(item.dict())
            else:
                result.append(dict(item))
        return result
    if isinstance(content, dict) and isinstance(content.get("items"), list):
        logger.info("[PARSER] 检测到 output_schema 格式，自动解包 items")
        return content["items"]
    if isinstance(content, list):
        logger.info("[PARSER] 检测到列表格式，直接使用")
        return content
    return []


def parse_json_mapping_result(content: Any) -> list[dict[str, Any]]:
    """解析字段映射模型结果，只保留三列并兼容既有容错格式。"""
    valid_columns = {"原始字段名", "系统属性名称", "匹配状态"}

    def validate_item(item: dict[str, Any]) -> bool:
        """验证并原地规范化一条字段映射记录。"""
        if not isinstance(item, dict):
            return False
        if set(item) != valid_columns:
            filtered = {key: value for key, value in item.items() if key in valid_columns}
            if len(filtered) != 3:
                return False
            item.clear()
            item.update(filtered)
        if item.get("系统属性名称") == "未匹配" and item.get("匹配状态") != "未匹配":
            logger.warning("[PARSER] 检测到未匹配状态矛盾并完成自动修正")
            item["匹配状态"] = "未匹配"
        return True

    logger.info(
        "[PARSER] 收到模型结果: content_type=%s content_length=%s",
        type(content).__name__,
        len(str(content)),
    )
    is_structured = (
        (hasattr(content, "items") and isinstance(getattr(content, "items"), list))
        or (isinstance(content, dict) and isinstance(content.get("items"), list))
        or isinstance(content, list)
    )
    items = _extract_mapping_items(content)
    if items or is_structured:
        logger.debug("[PARSER] 模型原始返回: %s", content)
        valid_result = [item for item in items if validate_item(item)]
        logger.info("[PARSER] Pydantic 对象解析成功，获得 %s 条有效记录", len(valid_result))
        return valid_result

    content_stripped = str(content).strip()
    try:
        result = json.loads(content_stripped)
        if isinstance(result, list):
            valid_result = [item for item in result if validate_item(item)]
            if valid_result:
                logger.info("[PARSER] 方法1解析成功，获得 %s 条有效记录", len(valid_result))
                return valid_result
    except json.JSONDecodeError:
        pass

    first_bracket = content_stripped.find("[")
    last_bracket = content_stripped.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        json_candidate = content_stripped[first_bracket : last_bracket + 1]
        logger.info("[PARSER] 方法2找到JSON候选，长度: %s", len(json_candidate))
        try:
            result = json.loads(json_candidate)
            if isinstance(result, list) and result:
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info("[PARSER] 方法2解析成功，获得 %s 条有效记录", len(valid_result))
                    return valid_result
        except json.JSONDecodeError as error:
            logger.warning("[PARSER] 方法2 JSON解析失败: %s", error)

    matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", content_stripped)
    logger.info("[PARSER] 方法3找到 %s 个代码块", len(matches))
    for match in matches:
        try:
            result = json.loads(match.strip())
            if isinstance(result, list):
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info("[PARSER] 方法3解析成功，获得 %s 条有效记录", len(valid_result))
                    return valid_result
        except json.JSONDecodeError:
            continue

    fixed_content = (
        content_stripped.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\uff08", "(")
        .replace("\uff09", ")")
    )
    if fixed_content != content_stripped:
        logger.info("[PARSER] 方法4：修复中文标点后重试")
        try:
            result = json.loads(fixed_content)
            if isinstance(result, list):
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info("[PARSER] 方法4解析成功，获得 %s 条有效记录", len(valid_result))
                    return valid_result
        except json.JSONDecodeError:
            pass

    item_pattern = (
        r'\{\s*"原始字段名"\s*:\s*"([^"]*)"\s*,\s*'
        r'"系统属性名称"\s*:\s*"([^"]*)"\s*,\s*'
        r'"匹配状态"\s*:\s*"([^"]*)"\s*\}'
    )
    regex_items = re.findall(item_pattern, content_stripped)
    if regex_items:
        logger.info("[PARSER] 方法5（regex逐项提取）成功，获得 %s 条记录", len(regex_items))
        result = [
            {"原始字段名": raw, "系统属性名称": standard, "匹配状态": status}
            for raw, standard, status in regex_items
        ]
        valid_result = [item for item in result if validate_item(item)]
        if valid_result:
            return valid_result

    if _is_mapping_refusal_response(content_stripped):
        logger.warning("[PARSER] 所有 JSON 解析均失败，且内容疑似拒绝响应（索要数据/无法处理），建议重试")
    else:
        logger.warning("[PARSER] 所有方法均解析失败，无法提取有效的映射结果")
    return []
