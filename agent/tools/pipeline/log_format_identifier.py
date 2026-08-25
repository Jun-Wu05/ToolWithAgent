# -*- coding: utf-8 -*-
"""
日志格式识别（Step 1）。

采样日志行 → 调用 LLM → 判定格式类型。
当前仅支持 JSON 格式，非 JSON 格式返回 UNSUPPORTED 状态。
"""

from __future__ import annotations

import json

import httpx
from agno.tools import tool

from agent.core.prompts import load_log_format_identify_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    _try_parse_json,
    normalize_log_format,
)

logger = get_logger("log_parser_pipeline")


def _strip_bodies(sampled: list[str], header_end_marker: str) -> list[str]:
    """按 header_end_marker 剥离日志头，返回每行的 body 文本。"""
    from agent.tools.pipeline.common.json_utils import strip_header_to_body

    if not header_end_marker:
        return list(sampled)
    return [strip_header_to_body(line, header_end_marker, is_json=False) for line in sampled]


def _enforce_format_consistency(parsed: dict, sampled: list[str]) -> None:
    """确定性一致性校验：LLM 报 JSON 但 body 无 JSON 对象、却呈 KV 结构时纠正为 KV。

    避免 RFC5424 syslog 头 + KV body（如 ``msg_type="x" host_ip="y"``）被 LLM 误判为
    「日志头+JSON」，导致 Step 2 走 JSON 聚合路径 matched=0。只在 body 确实不含
    ``{...}`` 且多数采样行像 key=value 对时才纠正；真正的 JSON 不受影响。
    """
    from agent.tools.pipeline.common.json_utils import extract_json_body
    from agent.tools.pipeline.extractors.kv_extractor import _DEFAULT_KV_PATTERN

    if parsed.get("format") != "JSON":
        return
    header_end_marker = parsed.get("header_end_marker", "") or ""
    # sample_logs 返回换行拼接的字符串，按行拆分后再剥离日志头。
    sampled_lines = [line for line in str(sampled).splitlines() if line.strip()]
    bodies = _strip_bodies(sampled_lines, header_end_marker)
    # 任一采样行含真实 JSON 对象 → 认可 LLM 的 JSON 判定，不纠正。
    if any(extract_json_body(body) for body in bodies):
        return
    # body 无 JSON 对象；统计呈 KV 结构（至少一个 key=value 对）的行数。
    kv_like = sum(1 for body in bodies if _DEFAULT_KV_PATTERN.search(body))
    if kv_like < max(1, len(bodies) // 2):
        return
    # 确定性检测分隔符：键值分隔符（= 或 :），字段分隔符（space / || / ;）。
    text = " ".join(bodies)
    tab = ":" if text.count(":") > text.count("=") else "="
    if "||" in text:
        delimit = "||"
    elif text.count(";") >= 2:
        delimit = ";"
    else:
        delimit = "space"
    parsed["format"] = "KV"
    parsed["format_detail"] = "日志头+KV" if header_end_marker else "KV"
    parsed["tab"] = tab
    parsed["delimit"] = delimit
    parsed["kv_connector"] = tab
    parsed["kv_separator"] = delimit
    logger.warning(
        "[identify_log_format] 一致性校验：LLM 报 JSON 但 body 无 JSON 对象、"
        f"呈 KV 结构，纠正为 KV（tab='{tab}', delimit='{delimit}'）"
    )


def _do_identify_log_format(logs_str: str) -> str:
    """采样日志并由 LLM 识别格式类型。

    参数:
        logs_str: 原始日志字符串（多行）

    返回:
        JSON 字符串，包含格式信息和置信度。
        非 JSON 格式时返回 status="UNSUPPORTED"。
    """
    if not logs_str or not logs_str.strip():
        return json.dumps(
            {"format": "unknown", "error": "日志内容为空", "confidence": 0},
            ensure_ascii=False,
        )

    try:
        # 采样 3 行供 LLM 分析
        sampled = sample_logs(logs_str, 3)
        if not sampled:
            return json.dumps(
                {"format": "unknown", "error": "采样结果为空", "confidence": 0},
                ensure_ascii=False,
            )

        prompt = load_log_format_identify_prompt().format(sampled_logs=sampled)
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=500, timeout=90)

        parsed = _try_parse_json(response)
        if parsed is None:
            logger.warning(f"[identify_log_format] LLM 返回非 JSON: {response[:200]}")
            return json.dumps(
                {
                    "format": "unknown",
                    "error": "LLM 返回非 JSON",
                    "raw_response": response[:500],
                    "confidence": 0,
                },
                ensure_ascii=False,
            )

        # 填充默认字段
        parsed.setdefault("format", "unknown")
        parsed.setdefault("format_detail", "unknown")
        parsed.setdefault("delimiter", None)
        parsed.setdefault("confidence", 0.5)
        parsed.setdefault("kv_connector", None)
        parsed.setdefault("kv_separator", None)
        parsed.setdefault("has_header", False)
        
        # CHANGED: KV 格式验证分隔符（2026-06-05 修复数据3失败问题）
        fmt = parsed.get("format", "").lower()
        if fmt == "kv":
            if "kv_connector" not in parsed or parsed["kv_connector"] is None:
                logger.warning("[identify_log_format] KV 格式但 LLM 未返回 kv_connector，将使用默认值尝试两种分隔符")
            if "kv_separator" not in parsed or parsed["kv_separator"] is None:
                logger.warning("[identify_log_format] KV 格式但 LLM 未返回 kv_separator，将使用默认值")
        
        # CHANGED: 将 LLM 返回的 kv_connector/kv_separator 映射为 tab/delimit
        # 语义：delimit=字段分隔符，tab=键值分隔符
        # kv_connector（LLM 输出）= 键值分隔符（如 = 或 :）→ tab
        # kv_separator（LLM 输出）= 字段分隔符（如 space、pipe）→ delimit
        if "kv_connector" in parsed and parsed["kv_connector"] is not None:
            parsed["tab"] = parsed["kv_connector"]  # 键值分隔符
        else:
            # CHANGED: LLM 未返回时，不设置 tab，让 Step 2 尝试两种分隔符
            pass
        
        # CHANGED: kv_separator 值映射（支持中文描述和代码格式）
        # 注意："space" 保持为字符串 "space"，让 KvExtractor 自动转为 \s+
        separator_map = {
            "空格": "space",     # 映射为 "space"，KvExtractor 会自动转为 \s+
            "space": "space",    # 保持为 "space"，KvExtractor 自动转为 \s+
            "分号": ";",
            "semicolon": ";",
            "逗号": ",",        # 英文逗号
            "comma": ",",
            "中文逗号": "，",   # 中文逗号
            "管道": "||",
            "pipe": "||",
            "tab": "\t",
        }
        if "kv_separator" in parsed and parsed["kv_separator"] in separator_map:
            parsed["delimit"] = separator_map[parsed["kv_separator"]]  # 字段分隔符
        elif "kv_separator" in parsed and parsed["kv_separator"] is not None:
            parsed["delimit"] = parsed["kv_separator"]
        else:
            # CHANGED: LLM 未返回时，不设置 delimit，让 Step 2 使用默认值
            pass
        parsed.setdefault("header_end_marker", "")
        parsed.setdefault("has_header_feature", False)  # CHANGED: 新增字段
        parsed.setdefault("feature_field", "")  # CHANGED: 新增字段
        parsed.setdefault("feature_location", "unknown")  # CHANGED: 新增字段
        parsed.setdefault("reason", "")

        # CHANGED: has_header=false 时强制 has_header_feature=false
        if not parsed.get("has_header"):
            parsed["has_header_feature"] = False

        # 归一化 format 字段为枚举值
        parsed["format"] = normalize_log_format(parsed.get("format", "unknown"))
        parsed.setdefault("format_detail", parsed.get("format_detail") or parsed.get("format", ""))

        # 确定性一致性校验：纠正 LLM 误报 JSON（body 实为 KV）的情况
        _enforce_format_consistency(parsed, sampled)

        # 确定性防护（PR #121 修复）：header_end_marker 等于字段分隔符时必为幻觉——
        # 它会把每行第一个字段（常为分类特征字段）当日志头剥掉。真实日志头标记
        # （如 " - "、": "）不会等于分隔符，不受影响。
        marker_value = str(parsed.get("header_end_marker", "") or "").strip()
        delimit_value = str(parsed.get("delimit", "") or "").strip()
        if marker_value and delimit_value and marker_value == delimit_value:
            logger.warning(
                f"[identify_log_format] header_end_marker='{marker_value}' 与字段分隔符相同，"
                f"判定为幻觉，已清空"
            )
            parsed["header_end_marker"] = ""

        # 非 JSON 格式标记为不支持
        if parsed["format"] == "unknown":
            logger.info(
                f"[identify_log_format] 无法识别的格式"
            )
            parsed["status"] = "UNSUPPORTED"
            parsed["reason"] = "无法识别日志格式"

        # CHANGED: 增强日志输出，显示 Step 1 识别的分隔符信息（2026-06-08 修复）
        logger.info(
            f"[identify_log_format] format={parsed['format']}, "
            f"has_header={parsed.get('has_header')}, "
            f"header_end_marker='{parsed.get('header_end_marker', '')}', "
            f"delimit='{parsed.get('delimit', '未识别')}', "
            f"tab='{parsed.get('tab', '未识别')}'"
        )

        # 如果是 KV 格式，额外输出原始字段
        if parsed['format'] == "kv":
            logger.info(
                f"[identify_log_format] KV 格式详细信息: "
                f"kv_connector='{parsed.get('kv_connector', '未返回')}', "
                f"kv_separator='{parsed.get('kv_separator', '未返回')}'"
            )

        return json.dumps(parsed, ensure_ascii=False)

    except httpx.HTTPStatusError as e:
        logger.error(f"[identify_log_format] API 错误: {e}")
        return json.dumps(
            {
                "format": "unknown",
                "error": f"LLM API 调用失败: {e.response.status_code}",
                "confidence": 0,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[identify_log_format] 异常: {type(e).__name__}: {e}")
        return json.dumps(
            {"format": "unknown", "error": str(e), "confidence": 0},
            ensure_ascii=False,
        )


@tool(
    name="identify_log_format",
    description="识别日志文本的格式类型。当前仅支持 JSON 格式。输入 logs_str=原始日志字符串，返回 JSON 格式信息。",
)
def identify_log_format(logs_str: str) -> str:
    """日志格式识别工具，委托给 _do_identify_log_format。"""
    return _do_identify_log_format(logs_str)