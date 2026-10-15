"""提供与界面无关的确定性 JSON 解析。"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from agent.shared.llm_response import parse_json_object
from agent.shared.logger import get_logger


logger = get_logger("parsers")

_MAPPING_REFUSAL_PATTERNS = [
    r"(?:请|需要|提供)(?:你|您|给我|输入)?.{0,10}(?:原始日志|日志样本|解码.{0,5}日志|更多数据|文件内容)",
    r"(?:无法|不能|不可以|没有足够).{0,10}(?:处理|映射|分析|完成|进行)",
    r"(?:需要先|必须先|必须).{0,15}(?:解码|查看|读取|获得)(?:原.{0,5}日志|样本|数据)",
    r"(?:缺少|缺失|不足).{0,10}(?:日志|样本|数据|内容|字段)",
    r"(?:请先|建议先).{0,15}(?:上传|提交|输入|补充)",
]

_THREAT_COLUMNS = frozenset({"mappingType", "orgValue", "mappingValue"})
_MAPPING_COLUMNS = frozenset({"原始字段名", "系统属性名称", "匹配状态"})


def _extract_structured_items(content: Any, logger_name: str) -> list[dict[str, Any]]:
    """从 Pydantic、output_schema 字典或列表中提取结构化记录。"""
    if hasattr(content, "items") and isinstance(content.items, list):
        logger.info("[%s] 检测到 Pydantic 对象，直接提取 items", logger_name)
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
        logger.info("[%s] 检测到 output_schema 格式，自动解包 items", logger_name)
        return content["items"]
    if isinstance(content, list):
        logger.info("[%s] 检测到列表格式，直接使用", logger_name)
        return content
    return []


def _has_structured_shape(content: Any) -> bool:
    """判断输入是否为结构化形态（Pydantic items、output_schema 字典或列表）。"""
    return bool(
        (hasattr(content, "items") and isinstance(getattr(content, "items"), list))
        or (isinstance(content, dict) and isinstance(content.get("items"), list))
        or isinstance(content, list)
    )


def _filter_valid_items(
    items: list[dict[str, Any]],
    valid_columns: frozenset[str],
    normalize_item: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """按三列白名单原地过滤条目，可选执行族内特有的规范化钩子。"""

    def is_valid(item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        if set(item) != valid_columns:
            filtered = {key: value for key, value in item.items() if key in valid_columns}
            if len(filtered) != 3:
                return False
            item.clear()
            item.update(filtered)
        if normalize_item is not None:
            normalize_item(item)
        return True

    return [item for item in items if is_valid(item)]


def _fix_mapping_contradiction(item: dict[str, Any]) -> None:
    """修正字段映射记录的未匹配矛盾：标准属性为「未匹配」时状态强制一致。"""
    if item.get("系统属性名称") == "未匹配" and item.get("匹配状态") != "未匹配":
        logger.warning("[PARSER] 检测到未匹配状态矛盾并完成自动修正")
        item["匹配状态"] = "未匹配"


def _parse_three_column_result(
    content: Any,
    *,
    logger_name: str,
    valid_columns: frozenset[str],
    failure_message: str,
    normalize_item: Callable[[dict[str, Any]], None] | None = None,
    structured_greedy: bool = False,
    json_unwrap: bool = True,
    items_subarray: bool = False,
    punctuation_retry: bool = False,
    regex_columns: tuple[str, str, str] | None = None,
    refusal_check: bool = False,
) -> list[dict[str, Any]]:
    """三列模型结果解析的唯一阶梯：结构化直取 → JSON 容错 → 族内特有兜底。

    威胁映射与字段映射两个公开入口消费同一阶梯，行为差异全部经参数声明：
    - ``structured_greedy``：结构化输入即便 0 条有效也立即返回（映射侧语义，
      空结果是合法的「无映射」）；关闭时须解析出非空有效条目才返回（威胁侧）。
    - ``json_unwrap``：各级 ``json.loads`` 结果是否经结构化解包（威胁侧），
      还是仅接受裸列表（映射侧）。
    - ``normalize_item``：条目通过列过滤后的族内规范化钩子（映射侧矛盾修正）。
    - ``items_subarray`` / ``punctuation_retry`` / ``regex_columns`` / ``refusal_check``：
      族内特有容错分支（items 子数组 / 中文标点修复 / 正则逐项 / 拒绝响应识别）。
    """

    def candidate_items(parsed: Any) -> list[dict[str, Any]]:
        if json_unwrap:
            return _extract_structured_items(parsed, logger_name)
        return parsed if isinstance(parsed, list) else []

    logger.info(
        "[%s] 收到模型结果: content_type=%s content_length=%s",
        logger_name,
        type(content).__name__,
        len(str(content)),
    )

    items = _extract_structured_items(content, logger_name)
    if structured_greedy:
        if items or _has_structured_shape(content):
            logger.debug("[%s] 模型原始返回: %s", logger_name, content)
            valid_result = _filter_valid_items(items, valid_columns, normalize_item)
            logger.info(
                "[%s] Pydantic 对象解析成功，获得 %s 条有效记录",
                logger_name,
                len(valid_result),
            )
            return valid_result
    elif items:
        valid_result = _filter_valid_items(items, valid_columns, normalize_item)
        if valid_result:
            logger.info(
                "[%s] Pydantic 对象解析成功，获得 %s 条有效记录",
                logger_name,
                len(valid_result),
            )
            return valid_result

    content_stripped = str(content).strip()
    try:
        items = candidate_items(json.loads(content_stripped))
        if items:
            valid_result = _filter_valid_items(items, valid_columns, normalize_item)
            if valid_result:
                logger.info(
                    "[%s] 方法1解析成功，获得 %s 条有效记录",
                    logger_name,
                    len(valid_result),
                )
                return valid_result
    except json.JSONDecodeError:
        pass

    first_bracket = content_stripped.find("[")
    last_bracket = content_stripped.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        json_candidate = content_stripped[first_bracket : last_bracket + 1]
        logger.info("[%s] 方法2找到JSON候选，长度: %s", logger_name, len(json_candidate))
        try:
            items = candidate_items(json.loads(json_candidate))
            if items:
                valid_result = _filter_valid_items(items, valid_columns, normalize_item)
                if valid_result:
                    logger.info(
                        "[%s] 方法2解析成功，获得 %s 条有效记录",
                        logger_name,
                        len(valid_result),
                    )
                    return valid_result
        except json.JSONDecodeError as error:
            logger.warning("[%s] 方法2 JSON解析失败: %s", logger_name, error)

    if items_subarray and first_bracket == -1:
        items_match = re.search(r'"items"\s*:\s*\[([\s\S]*?)\]', content_stripped)
        if items_match:
            items_candidate = "[" + items_match.group(1) + "]"
            logger.info(
                "[%s] 方法2.5 尝试解析 items 子数组，长度: %s",
                logger_name,
                len(items_candidate),
            )
            try:
                items_result = json.loads(items_candidate)
                if isinstance(items_result, list) and items_result:
                    valid_result = _filter_valid_items(
                        items_result, valid_columns, normalize_item
                    )
                    if valid_result:
                        logger.info(
                            "[%s] 方法2.5 解析成功，获得 %s 条有效记录",
                            logger_name,
                            len(valid_result),
                        )
                        return valid_result
            except json.JSONDecodeError as error:
                logger.warning("[%s] 方法2.5 JSON解析失败: %s", logger_name, error)

    matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", content_stripped)
    logger.info("[%s] 方法3找到 %s 个代码块", logger_name, len(matches))
    for match in matches:
        try:
            items = candidate_items(json.loads(match.strip()))
            if items:
                valid_result = _filter_valid_items(items, valid_columns, normalize_item)
                if valid_result:
                    logger.info(
                        "[%s] 方法3解析成功，获得 %s 条有效记录",
                        logger_name,
                        len(valid_result),
                    )
                    return valid_result
        except json.JSONDecodeError:
            continue

    if punctuation_retry:
        fixed_content = (
            content_stripped.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("\uff08", "(")
            .replace("\uff09", ")")
        )
        if fixed_content != content_stripped:
            logger.info("[%s] 方法4：修复中文标点后重试", logger_name)
            try:
                result = json.loads(fixed_content)
                if isinstance(result, list):
                    valid_result = _filter_valid_items(
                        result, valid_columns, normalize_item
                    )
                    if valid_result:
                        logger.info(
                            "[%s] 方法4解析成功，获得 %s 条有效记录",
                            logger_name,
                            len(valid_result),
                        )
                        return valid_result
            except json.JSONDecodeError:
                pass

    if regex_columns is not None:
        column_a, column_b, column_c = regex_columns
        item_pattern = (
            r'\{\s*"' + re.escape(column_a) + r'"\s*:\s*"([^"]*)"\s*,\s*'
            r'"' + re.escape(column_b) + r'"\s*:\s*"([^"]*)"\s*,\s*'
            r'"' + re.escape(column_c) + r'"\s*:\s*"([^"]*)"\s*\}'
        )
        regex_items = re.findall(item_pattern, content_stripped)
        if regex_items:
            logger.info(
                "[%s] 方法5（regex逐项提取）成功，获得 %s 条记录",
                logger_name,
                len(regex_items),
            )
            result = [
                {column_a: raw, column_b: standard, column_c: status}
                for raw, standard, status in regex_items
            ]
            valid_result = _filter_valid_items(result, valid_columns, normalize_item)
            if valid_result:
                return valid_result

    if refusal_check and _is_mapping_refusal_response(content_stripped):
        logger.warning(
            "[%s] 所有 JSON 解析均失败，且内容疑似拒绝响应（索要数据/无法处理），建议重试",
            logger_name,
        )
    else:
        logger.warning("[%s] %s", logger_name, failure_message)
    return []


def _is_mapping_refusal_response(content: str) -> bool:
    """检测字段映射模型是否以索要数据等拒绝文本代替结构化结果。"""
    return any(re.search(pattern, content.strip()) for pattern in _MAPPING_REFUSAL_PATTERNS)


def parse_json_safe(text: str) -> dict[str, Any] | None:
    """解析 JSON 对象，兼容 Markdown 代码块与正文中的对象片段。"""
    return parse_json_object(text, extract_block=True)


def parse_json_threat_result(content: Any) -> list[dict[str, Any]]:
    """解析威胁映射结果，只保留三列并兼容既有输出容错格式。"""
    return _parse_three_column_result(
        content,
        logger_name="THREAT_PARSER",
        valid_columns=_THREAT_COLUMNS,
        failure_message="解析失败，无法提取有效的威胁映射结果",
        items_subarray=True,
    )


def parse_json_mapping_result(content: Any) -> list[dict[str, Any]]:
    """解析字段映射模型结果，只保留三列并兼容既有容错格式。"""
    return _parse_three_column_result(
        content,
        logger_name="PARSER",
        valid_columns=_MAPPING_COLUMNS,
        failure_message="所有方法均解析失败，无法提取有效的映射结果",
        normalize_item=_fix_mapping_contradiction,
        structured_greedy=True,
        json_unwrap=False,
        punctuation_retry=True,
        regex_columns=("原始字段名", "系统属性名称", "匹配状态"),
        refusal_check=True,
    )
