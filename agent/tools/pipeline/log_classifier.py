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


# ─── Step 2 NEW: Auto-discover feature field (纯代码，确定性) ─────────────

# Blacklist of field names that should NEVER be used as log type classifiers.
# These are high-cardinality fields (IPs, timestamps, IDs) or structural fields.
_FEATURE_FIELD_BLACKLIST: set[str] = {
    "src_ip", "dst_ip", "source_ip", "dest_ip", "srcip", "dstip",
    "sip", "dip", "source_address", "dest_address",
    "src_port", "dst_port", "sport", "dport", "srcport", "dstport",
    "src_mac", "dst_mac",
    "timestamp", "time", "date", "datetime", "event_time", "start_time", "end_time",
    "session_id", "sessionid", "trace_id", "traceid", "request_id", "requestid",
    "uuid", "uid", "guid", "id",
    "message", "msg", "detail", "description", "raw_log", "log",
    "user", "username", "user_name", "account", "src_user", "dst_user",
    "src_ip_geo", "dst_ip_geo", "geo_city", "geo_country",
    "process_name", "process_path", "file_path", "file_name",
    "url", "uri", "path",
    "bytes", "packet", "payload", "content",
    "tag_", "topic_", "topic",
    "hostname", "host", "serial_number", "device_name",
}

# Name patterns that suggest a good classifier field (scored by regex match)
_FEATURE_NAME_PATTERNS: list[tuple[_re.Pattern, int]] = [
    (_re.compile(r'(?:log.?type|logtype|msg.?type|msgtype)', _re.I), 10),
    (_re.compile(r'(?:event.?type|eventtype|event_name)', _re.I), 9),
    (_re.compile(r'(?:alarm.?name|alarm_name|alarm.?type)', _re.I), 9),
    (_re.compile(r'(?:category|cat|alert|threat)', _re.I), 8),
    (_re.compile(r'(?:type|kind)', _re.I), 7),
    (_re.compile(r'(?:action|operation|method)', _re.I), 5),
    (_re.compile(r'(?:name)', _re.I), 3),
]


def _extract_syslog_appname(line: str) -> str | None:
    """
    Extract the APP-NAME (syslog keyword) from a BSD syslog header.
    
    Examples:
        '<221>May 21 14:09:05 ips IPS: src_ip=...' → 'IPS'
        '<14>1 2026-04-14T05:57:55Z host cloudwalker-suspicious-command 1 - body'
          → 'cloudwalker-suspicious-command' (from RFC5424 structured data)
    
    Returns:
        APP-NAME string or None if not a syslog line.
    """
    # BSD syslog: <PRI>Month DD HH:MM:SS hostname APP-NAME: body
    # Pattern: after hostname (word), before the colon
    m = _re.match(r'<\d+>\w+\s+\d+\s+\d+:\d+:\d+\s+\S+\s+(\S+?):\s', line)
    if m:
        return m.group(1)
    # RFC5424: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID - body
    m = _re.match(r'<\d+>\d+\s+\S+\s+\S+\s+(\S+)\s+\S+\s+\S+\s*-\s', line)
    if m:
        return m.group(1)
    return None


def _discover_candidate_fields(
    logs_str: str,
    format_type: str,
    format_info: dict | None = None,
    header_end_marker: str = "",
    max_lines: int = 500,
) -> list[dict]:
    """
    Scan log lines and discover fields that could serve as log type classifiers.
    
    Strategy:
      1. For header lines: check syslog APP-NAME uniqueness
      2. For body lines: parse all KV/JSON fields, count unique values per field
      3. Score each field by: name pattern, coverage, cardinality, value distribution
    
    Returns:
        List of candidate dicts sorted by score (best first), each with:
        {
            "field_name": str,       # field name (or "syslog_appname" for header keyword)
            "unique_count": int,     # number of unique values
            "total_count": int,      # total occurrences
            "coverage": float,       # fraction of lines that have this field
            "is_header": bool,       # True if this is a syslog header keyword
            "values": [(value, count), ...],  # top 20 values by count
            "samples": {value: [line, ...]},  # up to 2 sample lines per value
            "score": float,          # computed score (higher = better classifier)
        }
    """
    ft = (format_type or "").lower()
    lines = [l for l in logs_str.strip().split("\n") if l.strip()][:max_lines]
    total_lines = len(lines)
    if total_lines == 0:
        return []

    # ── 1. Check syslog APP-NAME (header keyword) ──
    header_candidates: list[dict] = []
    if format_info and format_info.get("has_header"):
        appname_counter: Counter[str] = Counter()
        appname_samples: dict[str, list[str]] = {}
        for line in lines:
            appname = _extract_syslog_appname(line)
            if appname:
                appname_counter[appname] += 1
                if appname not in appname_samples:
                    appname_samples[appname] = []
                if len(appname_samples[appname]) < 2:
                    appname_samples[appname].append(line[:300].strip())

        if len(appname_counter) >= 2:
            # Multiple syslog APP-NAMEs → good classifier candidate
            unique = len(appname_counter)
            total = sum(appname_counter.values())
            coverage = total / total_lines
            score = _score_candidate("syslog_appname", unique, total_lines, coverage)
            score += 15  # Boost: header keyword is highest priority per Dify
            header_candidates.append({
                "field_name": "syslog_appname",
                "unique_count": unique,
                "total_count": total,
                "coverage": coverage,
                "is_header": True,
                "values": appname_counter.most_common(20),
                "samples": appname_samples,
                "score": score,
            })

    # ── 2. Parse body fields and count value distributions ──
    body_candidates: list[dict] = []
    field_value_counter: dict[str, Counter] = {}
    field_value_samples: dict[str, dict[str, list[str]]] = {}
    field_line_count: dict[str, int] = {}

    for line in lines:
        # Separate header and body
        body = line
        if header_end_marker:
            parts = line.split(header_end_marker, 1)
            if len(parts) == 2:
                body = parts[1]

        # Extract all key-value pairs from body
        pairs: dict[str, str] = {}
        if ft == "json":
            try:
                obj = json.loads(body)
                if isinstance(obj, dict):
                    pairs = _flatten_json(obj)
            except (json.JSONDecodeError, ValueError):
                # Fallback: try JSON substring
                json_start = body.find("{")
                json_end = body.rfind("}")
                if json_start != -1 and json_end > json_start:
                    try:
                        obj = json.loads(body[json_start:json_end + 1])
                        if isinstance(obj, dict):
                            pairs = _flatten_json(obj)
                    except (json.JSONDecodeError, ValueError):
                        pass
        else:
            # KV / space / semicolon / comma / cef / unknown
            pairs = _extract_all_kv_pairs(body, ft, format_info)

        for key, value in pairs.items():
            key_lower = key.lower().strip()
            if key_lower in _FEATURE_FIELD_BLACKLIST:
                continue
            if len(value) > 120:  # Skip very long values (likely message/detail)
                continue
            if not value.strip():
                continue

            if key not in field_value_counter:
                field_value_counter[key] = Counter()
                field_value_samples[key] = {}
                field_line_count[key] = 0

            field_value_counter[key][value] += 1
            field_line_count[key] += 1

            if value not in field_value_samples[key]:
                field_value_samples[key][value] = []
            if len(field_value_samples[key][value]) < 2:
                field_value_samples[key][value].append(line[:300].strip())

    # Score each body field
    for key, counter in field_value_counter.items():
        unique = len(counter)
        total = field_line_count[key]
        coverage = total / total_lines

        # Filter: need at least 2 unique values and >= 30% coverage
        if unique < 2 or coverage < 0.3:
            continue
        # Filter: skip extremely high-cardinality fields (likely unique per line)
        if unique > total_lines * 0.8:
            continue

        score = _score_candidate(key, unique, total_lines, coverage)

        body_candidates.append({
            "field_name": key,
            "unique_count": unique,
            "total_count": total,
            "coverage": coverage,
            "is_header": False,
            "values": counter.most_common(20),
            "samples": field_value_samples.get(key, {}),
            "score": score,
        })

    # Combine and sort by score
    all_candidates = header_candidates + body_candidates
    all_candidates.sort(key=lambda c: c["score"], reverse=True)

    # Return top 10 candidates
    return all_candidates[:10]


def _score_candidate(field_name: str, unique_count: int, total_lines: int, coverage: float) -> float:
    """Score a candidate field for classifier quality."""
    score = 0.0

    # Name pattern bonus
    for pattern, bonus in _FEATURE_NAME_PATTERNS:
        if pattern.search(field_name):
            score += bonus
            break

    # Coverage bonus (prefer fields present in most lines)
    score += coverage * 10

    # Cardinality scoring: prefer 2-50 unique values
    if 2 <= unique_count <= 50:
        score += 5
    elif unique_count > 50:
        score -= 5  # Too granular

    # Distribution uniformity: prefer not one-value-dominant
    # (Checked by caller if needed)

    return score


def _flatten_json(obj: dict, prefix: str = "") -> dict[str, str]:
    """Flatten a JSON object to key→string value pairs (1 level deep)."""
    pairs: dict[str, str] = {}
    for k, v in obj.items():
        full_key = f"{prefix}{k}" if not prefix else k
        if isinstance(v, (dict, list)):
            continue  # Skip nested structures
        pairs[full_key] = str(v)
    return pairs


def _extract_all_kv_pairs(body: str, format_type: str, format_info: dict | None = None) -> dict[str, str]:
    """Extract ALL key=value pairs from a body line (not just one field)."""
    pairs: dict[str, str] = {}
    
    # Use regex to find all key=value patterns
    # Pattern: key="value", key='value', key=value
    for m in _re.finditer(r'(\w[\w./-]*)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))', body):
        key = m.group(1).strip()
        value = m.group(2) or m.group(3) or m.group(4) or ""
        if key and key not in pairs:
            pairs[key] = value.strip()

    # Also try colon-separated (key: value) if format is unknown
    if not pairs and format_type not in ("kv", "cef"):
        for m in _re.finditer(r'(\w[\w.-]*):\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))', body):
            key = m.group(1).strip()
            value = m.group(2) or m.group(3) or m.group(4) or ""
            if key and key not in pairs:
                pairs[key] = value.strip()

    return pairs


# ─── Step 2.5: 按业务字段聚合 (纯函数，无 LLM) ───────────────────────────

def _aggregate_by_log_type(
    logs_str: str,
    feature_field: str = "log_type",
    format_type: str = "json",
    format_info: dict | None = None,
    header_end_marker: str = "",
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
        header_end_marker: 日志头与 body 的分界标记（如 " - "），为空表示无头部

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
    format_type = (format_type or "").lower()
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    total_lines = len(lines)
    matched_lines = 0

    value_counter: Counter[str] = Counter()
    value_samples: dict[str, list[str]] = {}

    for line in lines:
        feature_value: Any = None

        # CHANGED: Multi-strategy extraction with header_end_marker support.
        # Strategy 1: Try KV/JSON body extraction with header separation
        if header_end_marker:
            # Separate header and body using marker
            parts = line.split(header_end_marker, 1)
            body = parts[1] if len(parts) == 2 else line
        else:
            body = line

        # Strategy 2: Extract from body based on format type
        if format_type == "json":
            body_value = _try_extract_json_feature(body, feature_field)
            # Fallback: try full line if body extraction failed
            if body_value is None and body != line:
                body_value = _try_extract_json_feature(line, feature_field)
        else:
            body_value = _try_extract_kv_feature(
                body, feature_field, format_type, format_info
            )
            # Fallback: try full line if body extraction failed
            if body_value is None and body != line:
                body_value = _try_extract_kv_feature(
                    line, feature_field, format_type, format_info
                )

        feature_value = body_value

        # Fallback: header_regex (may truncate, lowest priority)
        if feature_value is None:
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


# ─── Feature Identifier Auto-Generation (确定性代码) ─────────────────────

def _generate_feature_identifier(
    format_type: str,
    feature_field: str,
    feature_position: str,
    header_end_marker: str,
    sample_lines: list[str],
    known_values: set[str],
) -> tuple[str, int, int]:
    """
    根据格式类型和特征字段自动生成双捕获组正则。

    Strategy:
      - KV body: (body)(feature_value)  — Group1=日志主体, Group2=特征值
      - JSON body: (json_body)(feature_value)  — Group1=JSON主体, Group2=特征值
      - header keyword: infer from samples

    Returns:
        (regex_pattern, body_group_index, value_group_index)
        or ("", 0, 0) on failure.
    """
    ft = (format_type or "").lower()
    candidates: list[tuple[str, int, int]] = []

    if feature_position == "header_regex":
        # Feature is in header keyword — infer from samples
        candidates.extend(_infer_header_keyword_regex(sample_lines, known_values))
    else:
        # Feature is in body
        if ft == "json":
            # JSON body: match entire JSON object, extract feature field
            escaped_field = _re.escape(feature_field)
            candidates.append(
                (rf'(\{{.*?"{escaped_field}"\s*:\s*"([^"]+)".*?\}})', 1, 2)
            )
            # Broader fallback for nested JSON
            candidates.append(
                (rf'(\{{[\s\S]*?"{escaped_field}"\s*:\s*"([^"]+)"[\s\S]*?\}})', 1, 2)
            )
        else:
            # KV body: (body containing field)(field value)
            escaped_field = _re.escape(feature_field)

            # CHANGED: When header_end_marker is present, skip the header in
            # Group1 so it captures ONLY the body (not the syslog header).
            # Previously the regex was (.*?field="value".*) which captured
            # the entire line including header into Group1.
            # Now with marker, Group1 starts AFTER the marker:
            #   ".*<marker>(.*field="value".*)" → Group1 = body only
            if header_end_marker:
                escaped_marker = _re.escape(header_end_marker)
                # Pattern: field="value" — Group1=body after marker, Group2=value
                candidates.append(
                    (rf'.*{escaped_marker}(.*{escaped_field}="([^"]+)".*)', 1, 2)
                )
                # Pattern: field='value'
                candidates.append(
                    (rf".*{escaped_marker}(.*{escaped_field}='([^']+)'.*)", 1, 2)
                )
                # Pattern: field=value (unquoted)
                candidates.append(
                    (rf".*{escaped_marker}(.*{escaped_field}=([^\s,;|]+).*)", 1, 2)
                )
            else:
                # No header marker: entire line is body
                # Pattern: field="value" — Group1=all before+after, Group2=value
                candidates.append(
                    (rf'(.*?{escaped_field}="([^"]+)".*)', 1, 2)
                )
                # Pattern: field='value'
                candidates.append(
                    (rf"(.*?{escaped_field}='([^']+)'.*)", 1, 2)
                )
                # Pattern: field=value (unquoted)
                candidates.append(
                    (rf"(.*?{escaped_field}=([^\s,;|]+).*)", 1, 2)
                )

    # Validation loop: try each candidate against sample lines
    for regex_str, body_grp, val_grp in candidates:
        try:
            compiled = _re.compile(regex_str)
        except _re.error:
            continue

        verified_count = 0
        for sample in sample_lines[:10]:
            m = compiled.search(sample)
            if m and m.lastindex and m.lastindex >= max(body_grp, val_grp):
                extracted = m.group(val_grp)
                if extracted in known_values:
                    verified_count += 1

        # Accept if at least 1 sample verified against known values
        if verified_count > 0:
            logger.info(
                f"[generate_feature_identifier] Verified regex: "
                f"'{regex_str[:80]}' ({verified_count}/{min(len(sample_lines), 10)} samples)"
            )
            return regex_str, body_grp, val_grp

    logger.warning(
        f"[generate_feature_identifier] No verified regex found for "
        f"format={format_type}, field={feature_field}, position={feature_position}"
    )
    return "", 0, 0


def _infer_header_keyword_regex(
    sample_lines: list[str],
    known_values: set[str],
) -> list[tuple[str, int, int]]:
    """
    Infer header keyword regex from sample lines.
    Generates double-capture-group regex for syslog APP-NAME extraction.

    For syslog lines like:
        <221>May 21 14:09:05 ips IPS: src_ip=...
    The regex (\\S+):\\s+([\\S\\s]*) extracts:
        Group1=IPS (value), Group2=body (src_ip=...)

    Returns:
        List of (regex_pattern, body_group, value_group) candidates.
    """
    candidates: list[tuple[str, int, int]] = []

    if not known_values or not sample_lines:
        return candidates

    # Pattern: syslog APP-NAME extraction
    # Look for lines where known_values appear as the last word before ": " separator
    # This matches BSD syslog format: <PRI>timestamp hostname APP-NAME: body
    
    # Candidate 1: General syslog APP-NAME — captures keyword before ": " and body after
    # Group1 = APP-NAME (keyword = value), Group2 = body
    # This is the standard pattern for BSD syslog (启明星辰 IPS, etc.)
    # body_group=2, value_group=1
    candidates.append((r'(\S+):\s+([\S\s]*)', 2, 1))
    
    # Candidate 2: Try to validate with known values — more specific pattern
    for val in list(known_values)[:3]:
        escaped_val = _re.escape(val)
        # Pattern: known value appears as syslog keyword
        # body_group=2, value_group=1
        candidates.append((rf'({escaped_val}):\s+([\S\s]*)', 2, 1))

    return candidates


def _aggregate_by_syslog_appname(
    logs_str: str,
    format_type: str = "unknown",
) -> dict:
    """
    Aggregate logs by syslog APP-NAME (header keyword).
    Used when the auto-discover detects that the syslog APP-NAME is the
    best classifier (e.g., multiple keywords like IPS, WAF, DNS).

    Returns:
        Same structure as _aggregate_by_log_type().
    """
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    total_lines = len(lines)
    matched_lines = 0

    value_counter: Counter[str] = Counter()
    value_samples: dict[str, list[str]] = {}

    for line in lines:
        appname = _extract_syslog_appname(line)
        if appname is None:
            continue
        matched_lines += 1
        value_counter[appname] += 1
        if appname not in value_samples:
            value_samples[appname] = []
        if len(value_samples[appname]) < 3:
            sample = line[:300].strip()
            if sample not in value_samples[appname]:
                value_samples[appname].append(sample)

    values_dict: dict[str, dict] = {}
    for val, cnt in value_counter.most_common():
        values_dict[val] = {
            "count": cnt,
            "samples": value_samples.get(val, []),
        }

    return {
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "feature_field": "syslog_appname",
        "values": values_dict,
        "value_count": len(value_counter),
        "top_values": [v for v, _ in value_counter.most_common(20)],
    }


# ─── Step 3: 日志特征分类 (调 LLM) ─────────────────────────────────────

def _do_classify_log_features(
    logs_str: str,
    format_type: str = "unknown",
    format_detail: str = "",
    feature_field: str = "log_type",
    format_info: dict | None = None,
    header_end_marker: str = "",
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
        # ─── CHANGED: Auto-discover feature field (方案A核心变更) ───
        # Step 1 不再输出 feature_field，由代码扫描全量日志自动发现最佳分类字段
        logger.info(
            f"[classify_log_features] Auto-discovering feature field: "
            f"format={format_type}, has_header={format_info.get('has_header') if format_info else 'N/A'}"
        )
        
        candidates = _discover_candidate_fields(
            logs_str, format_type, format_info, header_end_marker,
        )
        
        # Select best candidate
        best_candidate = candidates[0] if candidates else None
        _is_header_feature = False
        
        if best_candidate:
            _discovered_field = best_candidate["field_name"]
            _is_header_feature = best_candidate.get("is_header", False)
            logger.info(
                f"[classify_log_features] Discovered feature field: "
                f"'{_discovered_field}' (is_header={_is_header_feature}, "
                f"unique={best_candidate['unique_count']}, "
                f"coverage={best_candidate['coverage']:.2f}, "
                f"score={best_candidate['score']:.1f})"
            )
            for i, c in enumerate(candidates[:3]):
                logger.info(
                    f"  Candidate #{i+1}: field='{c['field_name']}', "
                    f"unique={c['unique_count']}, coverage={c['coverage']:.2f}, "
                    f"score={c['score']:.1f}"
                )
        else:
            _discovered_field = feature_field
            logger.warning(
                f"[classify_log_features] No candidate fields discovered, "
                f"falling back to provided field: '{feature_field}'"
            )

        # ─── Aggregate using discovered field ───
        if _is_header_feature:
            aggregation = _aggregate_by_syslog_appname(logs_str, format_type=format_type)
            _effective_feature_field = _discovered_field
        else:
            aggregation = _aggregate_by_log_type(
                logs_str, _discovered_field, format_type=format_type, format_info=format_info,
                header_end_marker=header_end_marker,
            )
            _effective_feature_field = _discovered_field

        value_count = aggregation.get("value_count", 0)
        top_values = aggregation.get("top_values", [])
        total_lines = aggregation.get("total_lines", 0)
        matched_lines = aggregation.get("matched_lines", 0)

        if value_count == 0:
            logger.warning(
                f"[classify_log_features] 字段 '{_effective_feature_field}' 聚合无匹配，"
                f"将使用采样日志直接分析"
            )

        # 构建聚合文本供 LLM 分析
        agg_parts: list[str] = []
        agg_parts.append(
            f"总行数: {total_lines}, 匹配行数: {matched_lines}, 唯一值数: {value_count}"
        )
        agg_parts.append(f"业务分类字段: {_effective_feature_field}")
        if _is_header_feature:
            agg_parts.append("分类方式: 日志头部关键词（syslog APP-NAME）")
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
                f"纯函数未能按 '{_effective_feature_field}' 聚合，请直接从原始日志分析特征。"
            )

        aggregation_text = "\n".join(agg_parts)

        # 采样原始日志供 LLM 参考
        sampled_logs = sample_logs(logs_str, 5)

        prompt = load_log_classify_feature_prompt().format(
            format_type=format_type,
            format_detail=format_detail or format_type,
            feature_field=_effective_feature_field,
            aggregation_text=aggregation_text,
            sampled_logs=sampled_logs,
        )

        logger.info(
            f"[classify_log_features] 调用 LLM, format={format_type}, "
            f"feature_field={_effective_feature_field}, values={value_count}, "
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
        parsed.setdefault("feature_field", _effective_feature_field)
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

        # ─── Code-generated feature_identifier (确定性，覆盖 LLM 输出) ───
        _known_values = set(aggregation.get("values", {}).keys())
        _feature_position = "header_regex" if _is_header_feature else "kv_body"
        _sample_lines_for_regex = [l for l in logs_str.strip().split("\n") if l.strip()][:20]

        _code_regex, _code_body_grp, _code_val_grp = _generate_feature_identifier(
            format_type=format_type,
            feature_field=_effective_feature_field,
            feature_position=_feature_position,
            header_end_marker=header_end_marker,
            sample_lines=_sample_lines_for_regex,
            known_values=_known_values,
        )

        if _code_regex:
            logger.info(
                f"[classify_log_features] Using code-generated feature_identifier: "
                f"'{_code_regex[:80]}', body_group={_code_body_grp}, val_group={_code_val_grp}"
            )
            parsed["feature_identifier"] = _code_regex
            parsed["feature_body_group"] = _code_body_grp
            parsed["feature_value_group"] = _code_val_grp
        else:
            logger.info(
                "[classify_log_features] Code-generated regex failed, "
                "keeping LLM's feature_identifier"
            )

        # Store header_end_marker for Step 4 (fill_sample_logs)
        parsed["header_end_marker"] = header_end_marker

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

        # CHANGED: Fallback logtype correction using simple single-group regex.
        # When feature_identifier's multi-group regex fails (e.g., lastindex < val_group),
        # construct a simpler regex directly from feature_field to extract the correct value.
        # This handles cases where header_regex truncates values (e.g., cloudwalker-(\S+)
        # capturing only "suspicious-command") while the KV body has the full value
        # (e.g., msg_type="cloudwalker-suspicious-command").
        _ff = parsed.get("feature_field", _effective_feature_field)
        if _ff and parsed.get("classification_details"):
            # Try common KV patterns: field="value", field='value', field=value
            _fallback_patterns = [
                _re.compile(rf'{_re.escape(_ff)}="([^"]+)"'),   # field="value"
                _re.compile(rf"{_re.escape(_ff)}='([^']+)'"),   # field='value'
                _re.compile(rf'{_re.escape(_ff)}=([^\s,;\|]+)'), # field=value (unquoted)
            ]
            _corrected_count = 0
            for detail in parsed["classification_details"]:
                _sample = detail.get("sample", "")
                _llm_logtype = detail.get("logtype", "")
                if not _sample or not _llm_logtype:
                    continue
                # Skip if already corrected by the primary validation above
                if _llm_logtype in _known_values and _llm_logtype == detail.get("logtype", ""):
                    # Check if the logtype was already found correct by primary validation
                    pass
                for _pat in _fallback_patterns:
                    try:
                        _fm = _pat.search(_sample)
                        if _fm and _fm.group(1):
                            _extracted = _fm.group(1)
                            if _extracted != _llm_logtype:
                                logger.info(
                                    f"[classify_log_features] Fallback correcting logtype: "
                                    f"LLM='{_llm_logtype}' -> extracted='{_extracted}' "
                                    f"via pattern='{_pat.pattern}'"
                                )
                                detail["logtype"] = _extracted
                                _corrected_count += 1
                            break  # Found a match, no need to try other patterns
                    except (_re.error, IndexError) as _fb_err:
                        logger.warning(
                            f"[classify_log_features] Fallback regex error: {_fb_err}"
                        )
            if _corrected_count > 0:
                logger.info(
                    f"[classify_log_features] Fallback corrected {_corrected_count} logtype(s)"
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