# -*- coding: utf-8 -*-
"""
日志格式识别与特征提取 Pipeline

流程说明：
  Step 1: identify_log_format   — 采样 → LLM → 格式识别
  Step 2: aggregate_by_format   — 纯函数 → 按格式聚合
  Step 3: classify_log_features — LLM → 特征提取 + 分类（对齐 Dify 工作流）
  Step 4: fill_sample_logs      — 纯函数 → 用 matched_regex 替换样例日志

对齐 Dify 工作流：
  原始日志 → 抽样(3行) → LLM格式识别 → 按 log_type 聚合 → LLM分类（找业务分类字段）→ 正则替换样例
  
工具内部直接通过 httpx 调 LLM API，不走 Agno Agent 路由循环。
"""

from __future__ import annotations

import json
import re as _re
import time
from collections import Counter, OrderedDict
from typing import Any, Optional

import httpx
from agno.tools import tool

from agent.core.model_config import ModelConfig
from agent.tools.enum_extract_tool import sample_logs
from agent.shared.logger import get_logger

logger = get_logger("log_parser_pipeline")

# ============================================================================
# 内部工具：直接调 LLM API（零 Agno 开销）
# ============================================================================

_LLM_API_URL: str = ""
_LLM_API_KEY: str = ""


def _init_llm_config() -> None:
    """懒加载 LLM API 配置"""
    global _LLM_API_URL, _LLM_API_KEY
    if _LLM_API_URL:
        return
    _LLM_API_KEY = ModelConfig.get_api_key()
    if ModelConfig.MODEL_PROVIDER == "siliconflow":
        _LLM_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
    else:
        base = "https://api.deepseek.com"
        _LLM_API_URL = f"{base}/v1/chat/completions"


def _call_llm_direct(
    prompt: str,
    model_id: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    timeout: float = 60.0,
) -> str:
    """
    直接调 LLM API（httpx），跳过 Agno，零 Agent 路由开销。

    Args:
        prompt: 用户 prompt
        model_id: 模型 ID，默认使用配置的主模型
        temperature: 温度，默认 0.1 保证格式稳定
        max_tokens: 最大输出 token
        timeout: 超时秒数

    Returns:
        LLM 返回的文本内容

    Raises:
        httpx.HTTPStatusError: API 返回非 2xx
    """
    _init_llm_config()
    if model_id is None:
        model_id = ModelConfig.MAIN_MODEL

    start = time.time()
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    logger.info(
        f"[LLM_DIRECT] 调用 {_LLM_API_URL}, model={model_id}, prompt_len={len(prompt)}"
    )
    resp = httpx.post(
        _LLM_API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {_LLM_API_KEY}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    content: str = data["choices"][0]["message"]["content"]
    elapsed = time.time() - start
    usage = data.get("usage", {})
    logger.info(
        f"[LLM_DIRECT] 完成, elapsed={elapsed:.2f}s, "
        f"input_tokens={usage.get('prompt_tokens', '?')}, "
        f"output_tokens={usage.get('completion_tokens', '?')}"
    )
    return content


def _try_parse_json(text: str) -> dict | None:
    """尝试从 LLM 响应中提取 JSON"""
    text = text.strip()
    # 去掉可能的 markdown 代码块包装
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取第一个 { ... } 块
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


# ============================================================================
# Step 1: 日志格式识别 (工具内调 LLM)
# ============================================================================

_LOG_FORMAT_IDENTIFY_PROMPT = """你是安全日志格式分析专家。分析以下3条采样日志，识别日志格式类型。

采样日志：
```
{sampled_logs}
```

可能的格式类型：
- json: JSON 格式（每行一个 JSON 对象）
- kv: key=value 或 key="value" 键值对格式
- space: 空格分隔的多列格式（Syslog、防火墙日志、W3C日志）
- semicolon: 分号分隔格式
- comma: 逗号分隔格式（CSV）
- unknown: 无法识别

你需要同时判断日志是否有"日志头"特征（即日志行的前半部分是固定格式的时间戳+主机名+进程名等，后半部分才是 JSON/KV 结构体）。

【重要】判断业务分类字段（feature_field）的位置：
- 如果分类标识在日志头部固定位置（如 %%10SHELL/6/SHELL_CMD、%LINK-5-CHANGED、[FW]ACCEPT、TYPE=Login 等），feature_position 设为 "header_regex"，并输出能提取该标识的正则（用 () 捕获值）。
- 如果分类标识在 KV body 中（如 log_type=xxx、event_type=xxx），feature_position 设为 "kv_body"。
- 如果分类标识在固定列位置（CSV第N列等），feature_position 设为 "positional"，并给出 column_index。

输出 JSON（严格一行，不要有额外文字）：
{{"format":"json|kv|space|semicolon|comma|unknown","format_detail":"日志头+JSON|JSON|KV|日志头+KV|等","delimiter":"分隔符字符(space格式为空格)","confidence":0.0~1.0,"kv_connector":"key-value连接符(= 或 : 或 空格等)","kv_separator":"kv对之间的分隔符(空格或;或,等)","has_header":true|false,"has_header_feature":true|false,"space_count":0,"log_feature_field":"推测的业务分类字段名(如log_type/event_type/category/module_identifier等)","feature_position":"kv_body|header_regex|positional","feature_extract_regex":"当feature_position=header_regex时，用于从行中提取特征值的正则表达式(含一个捕获组)","reason":"判断理由"}}"""


def _do_identify_log_format(logs_str: str) -> str:
    """
    采样日志并由 LLM 识别格式类型（纯函数，供 chainlit_app 等直接调用）。

    Args:
        logs_str: 原始日志字符串（多行）

    Returns:
        JSON 字符串: {"format": "...", "delimiter": "...", "confidence": 0.95, ...}
    """
    if not logs_str or not logs_str.strip():
        return json.dumps(
            {"format": "unknown", "error": "日志内容为空", "confidence": 0},
            ensure_ascii=False,
        )

    try:
        # 采样 3 行供 LLM 分析（节省 token）
        sampled = sample_logs(logs_str, 3)
        if not sampled:
            return json.dumps(
                {"format": "unknown", "error": "采样结果为空", "confidence": 0},
                ensure_ascii=False,
            )

        prompt = _LOG_FORMAT_IDENTIFY_PROMPT.format(sampled_logs=sampled)
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

        # 标准化字段名
        parsed.setdefault("format", "unknown")
        parsed.setdefault("format_detail", "unknown")
        parsed.setdefault("delimiter", None)
        parsed.setdefault("confidence", 0.5)
        parsed.setdefault("kv_connector", None)
        parsed.setdefault("kv_separator", None)
        parsed.setdefault("has_header", False)
        parsed.setdefault("has_header_feature", False)
        parsed.setdefault("space_count", 0)
        parsed.setdefault("log_feature_field", None)
        parsed.setdefault("feature_position", "kv_body")
        parsed.setdefault("feature_extract_regex", None)
        parsed.setdefault("reason", "")

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
    description="识别日志文本的格式类型（json/kv/space/csv等）。输入 logs_str=原始日志字符串。返回 JSON 格式信息。",
)
def identify_log_format(logs_str: str) -> str:
    """Agno Agent 工具封装，委托给 _do_identify_log_format。"""
    return _do_identify_log_format(logs_str)


# ============================================================================
# Step 2: 按格式聚合 (纯函数，无 LLM)
# ============================================================================


def _aggregate_json(logs_str: str, indent: int = 4) -> dict:
    """聚合 JSON 格式日志：提取所有唯一 key path + 统计值"""
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    key_paths: OrderedDict[str, dict] = OrderedDict()
    total_lines = len(lines)
    matched_lines = 0

    for line in lines:
        try:
            obj = json.loads(line)
            matched_lines += 1
            _walk_json_keys(obj, "", key_paths)
        except json.JSONDecodeError:
            continue

    return {
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "fields": list(key_paths.values()),
    }


def _walk_json_keys(
    obj: Any, prefix: str, key_paths: OrderedDict[str, dict]
) -> None:
    """递归遍历 JSON 对象，收集所有 key path"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if path not in key_paths:
                key_paths[path] = {
                    "field_name": path,
                    "position": path,
                    "example_values": [],
                    "total_count": 0,
                }
            entry = key_paths[path]
            entry["total_count"] += 1
            if len(entry["example_values"]) < 5:
                val_str = str(v)[:100] if v is not None else "null"
                if val_str not in entry["example_values"]:
                    entry["example_values"].append(val_str)
            _walk_json_keys(v, path, key_paths)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _walk_json_keys(item, f"{prefix}[{i}]" if prefix else f"[{i}]", key_paths)


def _aggregate_kv(
    logs_str: str, kv_connector: str = "=", kv_separator: str = " "
) -> dict:
    """聚合 KV 格式日志"""
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    keys: OrderedDict[str, dict] = OrderedDict()
    total_lines = len(lines)
    matched_lines = 0

    for line in lines:
        pairs = _parse_kv_line(line, kv_connector, kv_separator)
        if not pairs:
            continue
        matched_lines += 1
        for k, v in pairs:
            if k not in keys:
                keys[k] = {
                    "field_name": k,
                    "position": k,
                    "example_values": [],
                    "total_count": 0,
                }
            entry = keys[k]
            entry["total_count"] += 1
            if len(entry["example_values"]) < 5:
                val_str = str(v)[:100] if v is not None else ""
                if val_str and val_str not in entry["example_values"]:
                    entry["example_values"].append(val_str)

    return {
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "fields": list(keys.values()),
    }


def _parse_kv_line(
    line: str, kv_connector: str = "=", kv_separator: str = " "
) -> list[tuple[str, str]]:
    """解析一行 KV 格式日志"""
    pairs: list[tuple[str, str]] = []
    tokens = _smart_split(line, kv_separator)
    for token in tokens:
        token = token.strip().strip('"').strip("'")
        if kv_connector in token:
            key, _, value = token.partition(kv_connector)
            key = key.strip().strip('"').strip("'").strip()
            value = value.strip().strip('"').strip("'").strip()
            if key:
                pairs.append((key, value))
    return pairs


def _smart_split(text: str, sep: str) -> list[str]:
    """智能拆分，考虑引号内的分隔符"""
    if sep == " ":
        parts = []
        current: list[str] = []
        in_quote = False
        quote_char = ""
        for ch in text:
            if ch in ('"', "'") and not in_quote:
                in_quote = True
                quote_char = ch
                current.append(ch)
            elif ch == quote_char and in_quote:
                in_quote = False
                current.append(ch)
            elif ch == sep and not in_quote:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current))
        return parts
    else:
        return text.split(sep)


def _aggregate_delimited(logs_str: str, delimiter: str) -> dict:
    """聚合分隔符格式日志（分号/逗号/Tab 等）"""
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    columns: OrderedDict[str, dict] = OrderedDict()
    total_lines = len(lines)
    matched_lines = 0

    for line in lines:
        tokens = _smart_split(line, delimiter)
        tokens = [t.strip().strip('"').strip("'") for t in tokens if t.strip()]
        if not tokens:
            continue
        matched_lines += 1
        for i, val in enumerate(tokens):
            col_name = f"col_{i}"
            if col_name not in columns:
                columns[col_name] = {
                    "field_name": col_name,
                    "position": i,
                    "example_values": [],
                    "total_count": 0,
                }
            entry = columns[col_name]
            entry["total_count"] += 1
            if len(entry["example_values"]) < 5 and val not in entry["example_values"]:
                entry["example_values"].append(val)

    return {
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "fields": list(columns.values()),
    }


def _aggregate_space(logs_str: str, space_count: int = 0) -> dict:
    """聚合空格分隔格式日志"""
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    columns: OrderedDict[str, dict] = OrderedDict()
    total_lines = len(lines)
    matched_lines = 0

    for line in lines:
        tokens = _re.split(r"\s+", line.strip())
        tokens = [t for t in tokens if t]
        if not tokens:
            continue
        matched_lines += 1
        for i, val in enumerate(tokens):
            col_name = f"col_{i}"
            if col_name not in columns:
                columns[col_name] = {
                    "field_name": col_name,
                    "position": i,
                    "example_values": [],
                    "total_count": 0,
                }
            entry = columns[col_name]
            entry["total_count"] += 1
            if len(entry["example_values"]) < 5 and val not in entry["example_values"]:
                entry["example_values"].append(val)

    return {
        "total_lines": total_lines,
        "matched_lines": matched_lines,
        "fields": list(columns.values()),
    }


def _aggregate_fallback(logs_str: str) -> dict:
    """无法识别格式时的兜底聚合"""
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    return {
        "total_lines": len(lines),
        "matched_lines": 0,
        "fields": [],
        "error": "无法识别日志格式，请手动指定",
    }


def aggregate_by_format(logs_str: str, format_info: dict) -> dict:
    """
    根据格式类型聚合日志，纯函数无 LLM 调用。

    Args:
        logs_str: 原始日志字符串
        format_info: identify_log_format 返回的格式信息

    Returns:
        {
            "total_lines": int,
            "matched_lines": int,
            "fields": [{"field_name": ..., "position": ..., "example_values": [...], "total_count": int}],
        }
    """
    fmt = format_info.get("format", "unknown")

    if fmt == "json":
        return _aggregate_json(logs_str, format_info.get("space_count", 4))
    elif fmt == "kv":
        return _aggregate_kv(
            logs_str,
            kv_connector=format_info.get("kv_connector", "="),
            kv_separator=format_info.get("kv_separator", " "),
        )
    elif fmt == "space":
        return _aggregate_space(logs_str, format_info.get("space_count", 0))
    elif fmt == "semicolon":
        return _aggregate_delimited(logs_str, ";")
    elif fmt == "comma":
        return _aggregate_delimited(logs_str, ",")
    else:
        return _aggregate_fallback(logs_str)


# ============================================================================
# Step 2.5: 按业务字段聚合 (纯函数，无 LLM)
#   对齐 Dify 工作流中"JSON格式日志聚合处理脚本"
# ============================================================================

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
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    total_lines = len(lines)
    matched_lines = 0

    value_counter: Counter[str] = Counter()
    value_samples: dict[str, list[str]] = {}

    for line in lines:
        feature_value: Any = None

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


def _try_extract_json_feature(line: str, feature_field: str) -> Any:
    """从一行 JSON 日志中提取 feature_field 的值（含日志头+JSON 子串回退）。"""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        # 支持"日志头+JSON"格式：提取第一个 { 到最后一个 } 之间的 JSON 子串
        json_start = line.find("{")
        json_end = line.rfind("}")
        if json_start != -1 and json_end > json_start:
            try:
                obj = json.loads(line[json_start:json_end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        else:
            return None
    return _get_nested_value(obj, feature_field)


def _try_extract_kv_feature(
    line: str,
    feature_field: str,
    format_type: str,
    format_info: dict | None = None,
) -> Any:
    """
    从非 JSON 日志行中提取 feature_field 的值。

    策略（按优先级）：
    1. semicolon/comma：按分隔符拆分 → 每个 token 按 key=value 解析
    2. kv：使用 format_info 中的 kv_connector/kv_separator
    3. space：用正则 /\S+=\S+/ 匹配 key=value 对
    4. cef：查找 CEF 扩展字段中的 key=value 对
    5. 兜底：遍历行中所有 key=value 对查找匹配
    """
    if format_info is None:
        format_info = {}

    pairs: dict[str, str] = {}

    # 【优先级 0】LLM 识别特征值在日志头部固定位置，用 LLM 生成的正则提取
    feature_position = format_info.get("feature_position", "kv_body")
    if feature_position == "header_regex":
        extract_regex = format_info.get("feature_extract_regex")
        if extract_regex:
            try:
                m = _re.search(extract_regex, line)
                if m:
                    return m.group(1) if m.lastindex else m.group(0)
            except _re.error:
                pass
    # 【优先级 0.5】positional: 按固定列位置提取
    if feature_position == "positional":
        column_index = format_info.get("column_index")
        if column_index is not None:
            try:
                col_idx = int(column_index)
                if format_type in ("semicolon", "comma"):
                    tokens = _smart_split(line, ";" if format_type == "semicolon" else ",")
                else:
                    tokens = _re.split(r"\s+", line.strip())
                tokens = [t for t in tokens if t]
                if 0 <= col_idx < len(tokens):
                    return tokens[col_idx].strip().strip('"').strip("'")
            except (ValueError, IndexError):
                pass

    if format_type == "semicolon":
        # 分号分隔 → 按 ; 拆分 → 每个 token 可能是 key=value
        tokens = line.split(";")
        for token in tokens:
            token = token.strip().strip('"').strip("'")
            _kv_from_token(token, pairs)
    elif format_type == "comma":
        # 逗号分隔 → 注意引号内的逗号
        tokens = _smart_split(line, ",")
        for token in tokens:
            token = token.strip().strip('"').strip("'")
            _kv_from_token(token, pairs)
    elif format_type == "kv":
        kv_connector = format_info.get("kv_connector", "=")
        kv_separator = format_info.get("kv_separator", " ")
        kv_pairs = _parse_kv_line(line, kv_connector, kv_separator)
        for k, v in kv_pairs:
            pairs[k] = v
    elif format_type == "space":
        # 空格分隔：先尝试按 key=value 正则匹配
        _kv_from_space_line(line, pairs)
        # 也尝试用 CEF 的 key=value 模式
        if feature_field not in pairs:
            _kv_from_cef_style(line, pairs)
    elif format_type == "cef":
        _kv_from_cef_style(line, pairs)
    else:
        # unknown：遍历所有可能的 key=value 对
        _kv_from_token(line, pairs)
        _kv_from_space_line(line, pairs)
        _kv_from_cef_style(line, pairs)

    # 查找 feature_field（支持嵌套路径如 "event.type"）
    field_parts = feature_field.split(".")
    for k, v in pairs.items():
        if k == field_parts[0]:
            return v
        # 如果 feature_field 是单字段路径但 key 以 / 分隔（如 SHELL/6/SHELL_CMD）
        if feature_field in k:
            return v

    # 如果没找到精确匹配，尝试模糊匹配：去掉前导路径部分
    for k, v in pairs.items():
        # e.g. SHELL/6/SHELL_CMD contains SHELL_CMD
        if "/" in feature_field:
            last_part = feature_field.rsplit("/", 1)[-1]
            if k == last_part:
                return v
        if "/" in k:
            last_part = k.rsplit("/", 1)[-1]
            if last_part == feature_field or last_part == feature_field.rsplit("/", 1)[-1]:
                return v

    return None


def _kv_from_token(token: str, pairs: dict[str, str]) -> None:
    """从一个 token 中提取 key=value 或 key:value 对。"""
    for connector in ("=", ":", " "):
        if connector in token:
            key, sep, value = token.partition(connector)
            key = key.strip().strip('"').strip("'").strip()
            value = value.strip().strip('"').strip("'").strip()
            if key and key not in pairs:
                pairs[key] = value
            return


def _kv_from_space_line(line: str, pairs: dict[str, str]) -> None:
    """从空格分隔的行中提取 key=value 对（正则匹配）。"""
    # 匹配 patterns like key=value 或 key="value" 或 key:value
    pattern = _re.compile(r'(\S+)([=:])(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
    for m in pattern.finditer(line):
        key = m.group(1).strip()
        value = m.group(3) or m.group(4) or m.group(5)
        if key and key not in pairs:
            pairs[key] = value


def _kv_from_cef_style(line: str, pairs: dict[str, str]) -> None:
    """
    从 CEF 风格的扩展字段中提取 key=value 对。
    CEF 格式: CEF:Version|Device Vendor|...|Extension
    Extension 为 key=value 空格分隔的对。
    """
    # 提取 CEF 扩展部分（最后一个 | 之后）
    if "|" in line:
        cef_parts = line.split("|")
        # CEF 扩展从第 8 个字段开始（下标 7）
        # 但常见的是最后一个 | 之后的所有内容
        extension = cef_parts[-1]
        # 按空格拆分扩展字段中的 key=value 对
        for token in extension.split():
            token = token.strip()
            if "=" in token and not token.startswith("="):
                key, sep, value = token.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in pairs:
                    pairs[key] = value

    # 同时也尝试按 key=value 正则匹配整行
    _kv_from_space_line(line, pairs)


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


def _build_fallback_details(aggregation: dict) -> list[dict]:
    """当 LLM 无法正常解析时，用纯函数构建兜底的 classification_details"""
    details: list[dict] = []
    for val, info in aggregation.get("values", {}).items():
        details.append({
            "value": val,
            "matched_regex": _re.escape(val),
            "meaning": "",
            "severity": "未知",
            "attack_type": "",
            "sample": info.get("samples", [None])[0] if info.get("samples") else "",
        })
    return details


# ============================================================================
# Step 3: 日志特征分类 (工具内调 LLM) — 对齐 Dify "JSON格式日志分类" 提示词
# ============================================================================

_CLASSIFY_FEATURE_PROMPT = """你是安全日志分析专家。请分析以下日志样本及其业务分类字段的聚合统计信息，识别各类日志的业务含义、攻击特征、分类和危害等级。

【格式信息】
- 格式类型：{format_type}
- 格式详情：{format_detail}
- 业务分类字段：{feature_field}

【业务分类字段聚合统计】
{aggregation_text}

【原始日志样本】（前 5 行）
```
{sampled_logs}
```

任务：
1. 分析日志结构，判断完整格式描述（如"日志头+JSON"、"纯JSON"、"KV"等）
2. 提取业务特征的唯一标识符（feature_identifier），即一个**双捕获组正则表达式**：
   - Group 1（第一个捕获组）：去掉日志头后的日志主体部分
   - Group 2（第二个捕获组）：{feature_field} 对应的字段值
   示例（日志头+JSON）：
     原始行: <8>Mar 26 12:06:20 localhost respond:{{... "log_type": "dac_dga_log" ...}}
     feature_identifier: (\\{{.*"{feature_field}":\\s"([^"]*)".*\\}})
     → Group 1 = JSON主体，Group 2 = dac_dga_log
   示例（日志头+文本）：
     原始行: <188>Sep 29 2024 03:10:15 host %%01IFPDT/4/IF_STATE(l)[48703]:Interface...UP state.
     feature_identifier: (?:%%|)(\\S+/\\d+/\\w+)(?:\\(\\w+\\)\\[\\d+\\]|\\[\\d+\\]|\\(\\w+\\)|):([\\S\\s]*)
     → Group 1 = 01IFPDT/4/IF_STATE，Group 2 = 后续消息体
   核心规则：Group 1 捕获去掉日志头的主体，Group 2 捕获 feature_field 的值。
3. 对每种业务分类值，分析其意义、匹配正则、危害等级

请严格按以下 JSON 格式输出（一行，不要额外文字）：
{{
  "status": "SUCCESS",
  "categorical_features": "分类特征名称",
  "Diversion_method": "日志分流方法",
  "log_format": "日志头+JSON 或 JSON 或 KV 或 日志头+KV",
  "feature_field": "业务分类字段名",
  "feature_identifier": "双捕获组正则：Group 1=去掉日志头后的日志主体，Group 2=feature_field的值",
  "feature_count": N,
  "classification_details": [
    {{"value": "字段值1", "matched_regex": "匹配该值的正则", "meaning": "业务含义", "severity": "严重/高危/中危/低危/信息", "attack_type": "攻击类型(如暴力破解/恶意软件/C2通信/信息泄露等)", "sample": "一行完整原始日志示例(不做截断)"}}
  ],
  "expert_summary": "综合分析摘要（100字以内）",
  "fail_reason": ""
}}"""


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
                "log_format": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": "",
                "feature_count": 0,
                "classification_details": [],
                "expert_summary": "日志内容为空",
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

        prompt = _CLASSIFY_FEATURE_PROMPT.format(
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
                    "log_format": format_detail or format_type,
                    "feature_field": feature_field,
                    "feature_identifier": "",
                    "feature_count": value_count,
                    "classification_details": _build_fallback_details(aggregation),
                    "expert_summary": f"LLM 返回格式异常，原始响应前 500 字: {response[:500]}",
                    "total_lines": total_lines,
                    "matched_lines": matched_lines,
                    "raw_response": response[:500],
                },
                ensure_ascii=False,
            )

        # 标准化输出字段
        parsed.setdefault("status", "SUCCESS")
        parsed.setdefault("log_format", format_detail or format_type)
        parsed.setdefault("feature_field", feature_field)
        parsed.setdefault("feature_identifier", "")
        parsed.setdefault("feature_count", value_count)
        parsed.setdefault("classification_details", [])
        parsed.setdefault("expert_summary", "")
        parsed.setdefault("categorical_features", "")
        parsed.setdefault("Diversion_method", "")
        parsed.setdefault("fail_reason", "")
        parsed.setdefault("total_lines", total_lines)
        parsed.setdefault("matched_lines", matched_lines)

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
                "log_format": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": "",
                "feature_count": 0,
                "classification_details": [],
                "expert_summary": f"API 错误: {e.response.status_code}",
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[classify_log_features] 异常: {type(e).__name__}: {e}")
        return json.dumps(
            {
                "status": "FAILED",
                "error": str(e),
                "log_format": format_detail or format_type,
                "feature_field": feature_field,
                "feature_identifier": "",
                "feature_count": 0,
                "classification_details": [],
                "expert_summary": f"异常: {str(e)[:200]}",
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


# ============================================================================
# Step 4: 替换样例日志 (纯函数)
#   用 classification_details 中的 matched_regex 从原始日志匹配真实样例
#   对齐 Dify 工作流中"替换样例日志"代码节点
# ============================================================================


def fill_sample_logs(
    classification: dict,
    logs_str: str,
    max_samples_per_type: int = 3,
) -> dict:
    """
    用分类结果中的 matched_regex 从原始日志匹配真实样例日志。

    对齐 Dify 工作流中"替换样例日志"代码节点的逻辑：
    对每个 classification_detail，用其 matched_regex 去原始日志中匹配真实行，
    替换模板占位符为真实日志行。

    Args:
        classification: classify_log_features 的输出 dict
        logs_str: 原始日志字符串
        max_samples_per_type: 每种分类最多取多少条真实样例

    Returns:
        classification 的副本，每个 classification_detail 增加 "real_samples" 列表
    """
    details = classification.get("classification_details", [])
    if not details:
        return classification

    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    result = dict(classification)
    result["classification_details"] = []

    for detail in details:
        detail_copy = dict(detail)
        matched_regex = detail_copy.get("matched_regex", "")
        detail_copy.setdefault("real_samples", [])

        if matched_regex:
            try:
                pattern = _re.compile(matched_regex)
                matched_count = 0
                for line in lines:
                    if pattern.search(line):
                        detail_copy["real_samples"].append(line[:300])
                        matched_count += 1
                        if matched_count >= max_samples_per_type:
                            break
            except _re.error as e:
                logger.warning(
                    f"[fill_sample_logs] 正则编译失败: {matched_regex}, 错误: {e}"
                )
                detail_copy["regex_error"] = str(e)

        # 如果正则匹配不到，回退用原始的 sample 字段
        if not detail_copy["real_samples"] and detail_copy.get("sample"):
            detail_copy["real_samples"] = [detail_copy["sample"]]

        result["classification_details"].append(detail_copy)

    return result