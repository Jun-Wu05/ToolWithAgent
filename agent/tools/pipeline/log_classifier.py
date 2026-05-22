# -*- coding: utf-8 -*-
"""
[Step 3] 日志特征分类 — 纯函数聚合 + LLM 特征分类。

提供 _do_classify_log_features() 和 classify_log_features(@tool)。
内部使用 _aggregate_by_log_type (Step 2.5) 做纯函数预聚合。
"""

from __future__ import annotations

import json
import re as _re
from collections import Counter
from typing import Any

import httpx
from agno.tools import tool

from agent.core.prompts import load_log_classify_feature_prompt
from agent.shared.logger import get_logger
from agent.tools.enum_extract_tool import sample_logs
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    _try_parse_json,
    normalize_log_format,
)
from agent.tools.pipeline.log_feature_extractor import (
    _try_extract_json_feature,
    _try_extract_kv_feature,
)

logger = get_logger("log_parser_pipeline")


def _normalize_log_format(format_type: str) -> str:
    """将 LLM 返回的格式类型映射为固定枚举值（JSON/KV/CEF/SEPARATOR/UNKNOWN）。"""
    return normalize_log_format(format_type)


# ─── Step 2.5: 按业务字段聚合 (纯函数，无 LLM) ───────────────────────────

def _aggregate_by_log_type(
    logs_str: str,
    feature_field: str = "log_type",
    format_type: str = "json",
    format_info: dict | None = None,
) -> dict:
    """
    按指定的业务分类字段值做纯函数聚合。

    支持多种日志格式：
    - json: 每行 JSON（含"日志头+JSON"子串回退）
    - kv: key=value 或 key:value 键值对
    - semicolon/comma: 分隔符格式，从中提取 key=value 对
    - space: 空格分隔格式，从中提取 key=value 对
    - cef: CEF 格式（CEF:Version|...|extensions=key value pairs）

    Args:
        logs_str: 原始日志字符串（多行）
        feature_field: 业务分类字段名，默认 "log_type"
        format_type: 日志格式类型 (json/kv/semicolon/comma/space/cef)
        format_info: identify_log_format 返回的完整格式信息

    Returns:
        {
            "total_lines": int,
            "matched_lines": int,
            "feature_field": str,
            "values": {
                "value_1": {"count": N, "samples": ["...", "..."]},
                ...
            },
            "value_count": int,
            "top_values": ["v1", "v2", ...],
        }
    """
    format_type = (format_type or "").lower()  # CHANGED: 归一化小写，防御 Step1 输出 "JSON" 等大写值
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    total_lines = len(lines)
    matched_lines = 0

    value_counter: Counter[str] = Counter()
    value_samples: dict[str, list[str]] = {}

    for line in lines:
        feature_value: Any = None

        # 优先级最高：header_regex 不依赖 format_type（日志头+JSON / 日志头+KV 均适用）
        if (
            format_info
            and format_info.get("feature_position") == "header_regex"
            and format_info.get("feature_extract_regex")
        ):
            try:
                m = _re.search(format_info["feature_extract_regex"], line)
                if m:
                    feature_value = m.group(1) if m.lastindex else m.group(0)
            except _re.error:
                pass

        # 回退到常规 JSON/KV body 提取
        if feature_value is None:
            if format_type == "json":
                feature_value = _try_extract_json_feature(line, feature_field)
            else:
                # 非 JSON 格式：从行中提取 key=value 对，找 feature_field
                feature_value = _try_extract_kv_feature(
                    line, feature_field, format_type, format_info
                )

        if feature_value is None:
            continue

        matched_lines += 1
        feature_str = str(feature_value)
        value_counter[feature_str] += 1

        if feature_str not in value_samples:
            value_samples[feature_str] = []
        if len(value_samples[feature_str]) < 3:
            sample = line[:200].strip()
            if sample not in value_samples[feature_str]:
                value_samples[feature_str].append(sample)

    # 构建输出
    values_dict: dict[str, dict] = {}
    for val, cnt in value_counter.most_common():
        values_dict[val] = {
            "count": cnt,
            "samples": value_samples.get(val, []),
        }

    return {
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "feature_field": feature_field,
        "values": values_dict,
        "value_count": len(value_counter),
        "top_values": [v for v, _ in value_counter.most_common(20)],
    }


def _extract_sample_summary(obj: dict) -> str:
    """提取 JSON 对象的核心字段值摘要（用于样本展示）"""
    # 优先取常见的关键字段
    priority_keys = [
        "log_type", "event_type", "category", "type",
        "action", "status", "severity", "message",
    ]
    parts: list[str] = []
    for key in priority_keys:
        val = _get_nested_value(obj, key)
        if val is not None:
            parts.append(f"{key}={val}")
    if not parts:
        # 取前 3 个非嵌套字段
        count = 0
        for k, v in obj.items():
            if not isinstance(v, (dict, list)):
                parts.append(f"{k}={v}")
                count += 1
                if count >= 3:
                    break
    return "; ".join(parts)


def _get_nested_value(obj: dict, path: str) -> Any:
    """从嵌套 JSON 对象中按点分隔路径获取值，如 'event.type'"""
    if not path:
        return None
    keys = path.split(".")
    current: Any = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return None
        else:
            return None
    return current


def _build_fallback_details(aggregation: dict) -> list[dict]:
    """当 LLM 无法正常解析时，用纯函数构建兜底的 classification_details"""
    details: list[dict] = []
    for val, info in aggregation.get("values", {}).items():
        details.append({
            "logtype": val,
            "sample": info.get("samples", [None])[0] if info.get("samples") else "",
        })
    return details


def _build_log_analysis(logs_str: str, format_type: str = "") -> dict:
    """分析日志结构特征（纯函数，不依赖 LLM）

    从原始日志前 5 行推断结构信息，用于补充 classification_details 的元数据。

    互斥规则（优先级从高到低）：
      CEF > JSON > KV > SEPARATOR
    只有主体格式对应的 bool 为 true，其余强制为 false。

    Args:
        logs_str: 原始日志字符串
        format_type: Step 1 识别的格式类型 (json/kv/cef 等)，用于修正启发式误判

    Returns:
        {
            "has_json_structure": bool,      # 互斥：只有 JSON 主体时为 true
            "has_cef_prefix": bool,          # 互斥：只有 CEF 主体时为 true
            "has_key_value_pairs": bool,     # 互斥：只有 KV 主体时为 true
            "has_delimited_structure": bool, # 互斥：只有分隔符主体时为 true
            "delimit": str,                  # key-value 连接符 (":" 或 "=")
            "tab": str,                      # 字段分隔符 ("," / ";" / "|" / "space")
        }
    """
    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:5]
    if not lines:
        return {
            "has_json_structure": False,
            "has_cef_prefix": False,
            "has_key_value_pairs": False,
            "has_delimited_structure": False,
            "delimit": ":",
            "tab": "space",
        }
    text = " ".join(lines)

    # ---- 互斥检测（优先级 CEF > JSON > KV > SEPARATOR） ----

    has_cef = any(l.strip().startswith("CEF:") for l in lines)
    has_json = bool(_re.search(r'\{[^}]*"[^}]*"[^}]*\}', text))

    # Token-level KV detection: split by whitespace and common field delimiters,
    # then check per-token K/V patterns.  Key must start with a letter or underscore
    # to avoid false positives on timestamps (09:46:01) and IPv6 (2409:8a18).
    tokens: list[str] = _re.split(r'[\s,;|]+', text)
    tokens = [t for t in tokens if t.strip()]

    if tokens:
        kv_equal = _re.compile(r'^[a-zA-Z_]\w*=')
        kv_colon = _re.compile(r'^[a-zA-Z_]\w*:')
        kv_slash = _re.compile(r'^[a-zA-Z]\w*/')
        kv_count = sum(
            1 for t in tokens
            if kv_equal.search(t) or kv_colon.search(t) or kv_slash.search(t)
        )
        has_kv = kv_count / len(tokens) >= 0.25
    else:
        has_kv = False

    has_delim = len(_re.findall(r'[,;|]', text)) >= 1

    # 互斥：按优先级保留最高优先级的格式
    if has_cef:
        has_json = False
        has_kv = False
        has_delim = False
    elif has_json:
        has_kv = False
        has_delim = False
    elif has_kv:
        has_delim = False
    # has_delim 保留原值（最低优先级）

    # CHANGED: Use format_type from Step 1 to override heuristic detection.
    # When Step 1 identified the format as KV/UNKNOWN, embedded JSON values
    # (e.g., process_tree=[{...}], env=[...]) should NOT trigger has_json_structure.
    # Unconditionally force has_json=False and has_kv=True when Step 1 says KV.
    if format_type and format_type.lower() in ("kv", "unknown"):
        if has_json:
            has_json = False
            if not has_kv:
                has_kv = True

    # 猜测 key-value 连接符
    eq_count = text.count("=")
    colon_count = text.count(":")
    delimit = "=" if eq_count >= colon_count else ":"

    # 猜测字段分隔符
    delim_counts: dict[str, int] = {
        ",": text.count(","),
        ";": text.count(";"),
        "|": text.count("|"),
        "\t": text.count("\t"),
    }
    max_delim = max(delim_counts, key=delim_counts.get)  # type: ignore[arg-type]
    tab = max_delim if delim_counts[max_delim] > 0 else "space"  # type: ignore[index]

    return {
        "has_json_structure": has_json,
        "has_cef_prefix": has_cef,
        "has_key_value_pairs": has_kv,
        "has_delimited_structure": has_delim,
        "delimit": delimit,
        "tab": tab if isinstance(tab, str) else "space",
    }


# ─── Step 3: 日志特征分类 (调 LLM) ─────────────────────────────────────

def _do_classify_log_features(
    logs_str: str,
    format_type: str = "unknown",
    format_detail: str = "",
    feature_field: str = "log_type",
    format_info: dict | None = None,
) -> str:
    """
    解析日志、聚合、调 LLM 分类（纯函数，供 chainlit_app 等直接调用）。

    Args:
        logs_str: 原始日志字符串
        format_type: 格式类型 (json/kv/space)
        format_detail: 格式详情
        feature_field: 业务分类字段名
        format_info: identify_log_format 返回的完整格式信息（含 feature_position 等）

    Returns:
        JSON 字符串
    """
    if not logs_str or not logs_str.strip():
        return json.dumps(
            {
                "status": "FAILED",
                "error": "日志内容为空",
                "log_format": _normalize_log_format(format_type),
                "log_format_detail": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": "",
                "feature_count": 0,
                "total_valid_lines": 0,
                "covered_lines": 0,
                "classification_details": [],
            },
            ensure_ascii=False,
        )

    try:
        # 按业务字段聚合（传入 format_type + format_info 以支持 header_regex 提取）
        aggregation = _aggregate_by_log_type(
            logs_str, feature_field, format_type=format_type, format_info=format_info
        )
        value_count = aggregation.get("value_count", 0)
        top_values = aggregation.get("top_values", [])
        total_lines = aggregation.get("total_lines", 0)
        matched_lines = aggregation.get("matched_lines", 0)

        if value_count == 0:
            logger.warning(
                f"[classify_log_features] 字段 '{feature_field}' 纯函数聚合无匹配，"
                f"将继续调 LLM 直接分析原始日志"
            )

        # 构建聚合文本供 LLM 分析
        agg_parts: list[str] = []
        agg_parts.append(
            f"总行数: {total_lines}, 匹配行数: {matched_lines}, 唯一值数: {value_count}"
        )
        agg_parts.append(f"业务分类字段: {feature_field}")
        agg_parts.append("")
        if value_count > 0:
            agg_parts.append("各值统计（TOP 20）：")
            for val in top_values:
                info = aggregation["values"].get(val, {})
                cnt = info.get("count", 0)
                samples = info.get("samples", [])
                sample_str = " | ".join(samples[:2]) if samples else "无样本"
                agg_parts.append(f"  {val}: 出现 {cnt} 次 | 样本: {sample_str}")
        else:
            agg_parts.append(
                f"纯函数未能按 '{feature_field}' 聚合，请直接从原始日志分析特征。"
            )

        aggregation_text = "\n".join(agg_parts)

        # 采样原始日志供 LLM 参考
        sampled_logs = sample_logs(logs_str, 5)

        prompt = load_log_classify_feature_prompt().format(
            format_type=format_type,
            format_detail=format_detail or format_type,
            feature_field=feature_field,
            aggregation_text=aggregation_text,
            sampled_logs=sampled_logs,
        )

        logger.info(
            f"[classify_log_features] 调用 LLM, format={format_type}, "
            f"feature_field={feature_field}, values={value_count}, "
            f"prompt_len={len(prompt)}"
        )
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=4000, timeout=90)

        parsed = _try_parse_json(response)
        if parsed is None:
            logger.warning(f"[classify_log_features] LLM 返回非 JSON: {response[:200]}")
            return json.dumps(
                {
                    "status": "PARTIAL",
                    "error": "LLM 返回非 JSON",
                    "log_format": _normalize_log_format(format_type),
                    "log_format_detail": format_detail or format_type,
                    "feature_field": feature_field,
                    "feature_identifier": "",
                    "feature_count": value_count,
                    "total_valid_lines": total_lines,
                    "covered_lines": matched_lines,
                    "classification_details": _build_fallback_details(aggregation),
                    "raw_response": response[:500],
                },
                ensure_ascii=False,
            )

        # 标准化输出字段
        parsed.setdefault("status", "SUCCESS")
        # CHANGED: 强制用归一化枚举值覆盖 LLM 输出，确保 log_format 始终为固定枚举
        parsed["log_format"] = _normalize_log_format(format_type)
        parsed.setdefault("log_format_detail", format_detail or format_type)
        parsed.setdefault("feature_field", feature_field)
        parsed.setdefault("feature_identifier", "")
        parsed.setdefault("feature_count", value_count)
        # CHANGED: total_lines/matched_lines 改名为 total_valid_lines/covered_lines 后，需显式写入输出
        parsed.setdefault("total_valid_lines", total_lines)
        parsed.setdefault("covered_lines", matched_lines)
        parsed.setdefault("classification_details", [])
        parsed.setdefault("categorical_features", "")
        parsed.setdefault("Diversion_method", "")
        # CHANGED: Always overwrite LLM's "analysis" with heuristic result.
        # LLM may misdetect KV logs with embedded JSON arrays (e.g., process_tree=[...])
        # as having JSON structure. The heuristic _build_log_analysis() already applies
        # format_type-based correction (Fix 1), so its result must take precedence.
        parsed["analysis"] = _build_log_analysis(logs_str, format_type=format_type)

        # CHANGED: 确保 classification_details 覆盖 aggregation 中所有已知分类值
        # 防御 LLM 遗漏低频分类（如 ssoaccess 占比 0.46% 被忽略）
        _known_values = set(aggregation.get("values", {}).keys())
        _existing_logtypes = {
            d.get("logtype") for d in parsed.get("classification_details", []) if d.get("logtype")
        }

        # 防御 LLM 新增无关分类（如按 username 而不是 feature_field 分类）
        _extra_values = _existing_logtypes - _known_values
        if _extra_values:
            logger.warning(
                f"[classify_log_features] LLM 新增了不在 aggregation 中的分类值: {_extra_values}，"
                f"已自动剔除"
            )
            parsed["classification_details"] = [
                d for d in parsed.get("classification_details", [])
                if d.get("logtype") in _known_values
            ]

        _missing_values = _known_values - _existing_logtypes
        if _missing_values:
            logger.warning(
                f"[classify_log_features] LLM 遗漏 classification_details: {_missing_values}，"
                f"自动补充"
            )
            for _val in sorted(_missing_values):
                _info = aggregation["values"].get(_val, {})
                _samples = _info.get("samples", [])
                _sample = _samples[0] if _samples else ""
                parsed["classification_details"].append({
                    "logtype": _val,
                    "sample": _sample,
                })

        # CHANGED: 始终同步 feature_count 为实际 classification_details 长度
        parsed["feature_count"] = len(parsed["classification_details"])

        # CHANGED: Validate logtype against feature_identifier regex extraction.
        # LLM may truncate or misidentify the logtype (e.g., "suspicious-command"
        # instead of "cloudwalker-suspicious-command"). Re-extract the actual
        # feature value from each sample using the regex.
        _feat_id = parsed.get("feature_identifier", "")
        _raw_val_group = parsed.get("feature_value_group", 0) or 0
        # CHANGED: Defensive int() conversion — LLM may return string "2" instead of int 2.
        # TypeError from str vs int comparison would silently skip correction.
        try:
            _val_group = int(_raw_val_group)
        except (TypeError, ValueError):
            logger.warning(
                f"[classify_log_features] feature_value_group is not int: "
                f"{type(_raw_val_group).__name__} '{_raw_val_group}', defaulting to 0"
            )
            _val_group = 0

        logger.info(
            f"[classify_log_features] logtype validation: "
            f"feature_identifier='{_feat_id[:80]}', "
            f"feature_value_group={_val_group} (raw={_raw_val_group!r}), "
            f"known_values={_known_values}, "
            f"details_count={len(parsed.get('classification_details', []))}"
        )

        if _feat_id and _val_group:
            for detail in parsed.get("classification_details", []):
                _sample = detail.get("sample", "")
                _llm_logtype = detail.get("logtype", "")
                if not _sample:
                    logger.info(
                        f"[classify_log_features] Skipping detail with empty sample, "
                        f"logtype='{_llm_logtype}'"
                    )
                    continue
                try:
                    _m = _re.search(_feat_id, _sample)
                    if _m is None:
                        logger.info(
                            f"[classify_log_features] Regex did not match sample "
                            f"for logtype='{_llm_logtype}', sample_len={len(_sample)}"
                        )
                        continue
                    if _m.lastindex is None or _m.lastindex < _val_group:
                        logger.info(
                            f"[classify_log_features] Regex matched but not enough groups: "
                            f"lastindex={_m.lastindex}, need={_val_group}, "
                            f"logtype='{_llm_logtype}'"
                        )
                        continue
                    _actual_value = _m.group(_val_group)
                    if _actual_value and _actual_value != _llm_logtype:
                        logger.info(
                            f"[classify_log_features] Correcting logtype: "
                            f"LLM='{_llm_logtype}' -> regex='{_actual_value}'"
                        )
                        detail["logtype"] = _actual_value
                    elif _actual_value == _llm_logtype:
                        logger.info(
                            f"[classify_log_features] logtype already correct: "
                            f"'{_llm_logtype}'"
                        )
                    else:
                        logger.info(
                            f"[classify_log_features] Regex extracted empty value "
                            f"for logtype='{_llm_logtype}'"
                        )
                except (_re.error, IndexError, TypeError) as _err:
                    logger.warning(
                        f"[classify_log_features] logtype regex validation error: "
                        f"{type(_err).__name__}: {_err}, logtype='{_llm_logtype}'"
                    )
        else:
            logger.info(
                f"[classify_log_features] Skipping logtype validation: "
                f"feature_identifier={'set' if _feat_id else 'empty'}, "
                f"feature_value_group={_val_group}"
            )

        # ====================================================================
        # 成功解析后自动存入向量知识库（失败不影响主流程）
        # ====================================================================
        if parsed.get("status") == "SUCCESS":
            try:
                from agent.tools.log_pattern_store import (
                    generate_structured_fingerprint,
                    store_log_knowledge,
                )

                structured_fp = generate_structured_fingerprint(
                    classify_result=parsed,
                    format_detail=format_detail,
                    feature_field=feature_field,
                )
                if structured_fp:
                    sample_lines = [
                        l for l in logs_str.strip().split("\n") if l.strip()
                    ][:10]
                    store_log_knowledge(
                        fingerprint=structured_fp,
                        format_type=format_type,
                        meta=parsed,
                        sample_logs=sample_lines,
                    )
                    logger.info(
                        f"[classify_log_features] 知识库存储成功: "
                        f"{structured_fp[:80]}..."
                    )
            except Exception as store_err:
                logger.warning(
                    f"[classify_log_features] 知识库存储失败（不影响主流程）: "
                    f"{store_err}"
                )

        return json.dumps(parsed, ensure_ascii=False)

    except httpx.HTTPStatusError as e:
        logger.error(f"[classify_log_features] API 错误: {e}")
        return json.dumps(
            {
                "status": "FAILED",
                "error": f"LLM API 调用失败: {e.response.status_code}",
                "log_format": _normalize_log_format(format_type),
                "log_format_detail": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": "",
                "feature_count": 0,
                "total_valid_lines": 0,
                "covered_lines": 0,
                "classification_details": [],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[classify_log_features] 异常: {type(e).__name__}: {e}")
        return json.dumps(
            {
                "status": "FAILED",
                "error": str(e),
                "log_format": _normalize_log_format(format_type),
                "log_format_detail": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": "",
                "feature_count": 0,
                "total_valid_lines": 0,
                "covered_lines": 0,
                "classification_details": [],
            },
            ensure_ascii=False,
        )


@tool(
    name="classify_log_features",
    description="识别日志的业务分类特征。输入 logs_str=原始日志字符串, format_type=格式类型, format_detail=格式详情。对齐 Dify 工作流找业务分类字段。",
)
def classify_log_features(
    logs_str: str,
    format_type: str = "unknown",
    format_detail: str = "",
    feature_field: str = "log_type",
) -> str:
    """Agno Agent 工具封装，委托给 _do_classify_log_features。"""
    return _do_classify_log_features(logs_str, format_type, format_detail, feature_field)