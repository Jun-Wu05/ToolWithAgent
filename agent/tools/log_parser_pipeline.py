# -*- coding: utf-8 -*-
"""
日志格式识别与特征提取 Pipeline

参考 Dify 流实现：
  Step 1: identify_log_format   — 采样 → LLM → 格式识别
  Step 2: aggregate_by_format   — 纯函数 → 按格式聚合
  Step 3: classify_aggregated   — LLM → 特征提取 + 分类
  Step 4: fill_sample_logs      — 纯函数 → 替换样例日志

工具内部直接通过 httpx 调 LLM API，不走 Agno Agent 路由循环。
"""

from __future__ import annotations

import json
import re as _re
import time
from collections import OrderedDict
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

输出 JSON（严格一行，不要有额外文字）：
{{"format":"json|kv|space|semicolon|comma|unknown","delimiter":"分隔符字符(space格式为空格)","confidence":0.0~1.0,"kv_connector":"key-value连接符(= 或 : 或 空格等)","kv_separator":"kv对之间的分隔符(空格或;或,等)","has_header":true|false,"space_count":0,"reason":"判断理由"}}"""


@tool(
    name="identify_log_format",
    description="识别日志文本的格式类型（json/kv/space/csv等）。输入 logs_str=原始日志字符串。返回 JSON 格式信息。",
)
def identify_log_format(logs_str: str) -> str:
    """
    采样日志并由 LLM 识别格式类型。

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
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=500, timeout=30)

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
        parsed.setdefault("delimiter", None)
        parsed.setdefault("confidence", 0.5)
        parsed.setdefault("kv_connector", None)
        parsed.setdefault("kv_separator", None)
        parsed.setdefault("has_header", False)
        parsed.setdefault("space_count", 0)
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
    # 尝试按 kv_separator 拆分
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
        # 对空格分隔，保护引号内内容
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
        # 非空格分隔符直接 split
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
# Step 3: 日志特征提取 + 分类 (工具内调 LLM)
# ============================================================================

_CLASSIFY_JSON_PROMPT = """你是安全日志分析专家。分析已聚合的 JSON 格式日志。

聚合结果：
{aggregated_json}

请为每个字段提取以下信息：
1. field_name: 字段名（使用 JSON path）
2. field_type: 字段类型（ip/port/protocol/time/status/action/severity/category/message/id/number/device/user/url/string）
3. aliases: 可能的别名列表（如 srcIp 的别名: ["源IP","source_ip","sip"]）
4. position: 在日志中的位置路径
5. example_values: 3-5 个样本值
6. total_count: 总出现次数
7. unique_count: 去重后的数量（可估计）

输出 JSON（严格一行）：
{{"fields": [{{"field_name":"...","field_type":"...","aliases":["...],"position":"...","example_values":["..."],"total_count":N,"unique_count":N}}], "sample_raw_log": "一条原始日志示例", "matched_lines": N, "total_lines": N}}"""

_CLASSIFY_KV_PROMPT = """你是安全日志分析专家。分析已聚合的 KV 键值对格式日志。

聚合结果：
{aggregated_json}

请为每个 key 提取以下信息：
1. field_name: 键名（从日志中提取的原始键名）
2. field_type: 值类型（ip/port/protocol/time/status/action/severity/category/message/id/number/device/user/url/string）
3. aliases: 可能的别名列表
4. position: 在日志中的位置（键名）
5. example_values: 3-5 个样本值
6. total_count: 总出现次数
7. unique_count: 去重后的数量（可估计）

输出 JSON（严格一行）：
{{"fields": [{{"field_name":"...","field_type":"...","aliases":["..."],"position":"...","example_values":["..."],"total_count":N,"unique_count":N}}], "sample_raw_log": "一条原始日志示例", "matched_lines": N, "total_lines": N}}"""

_CLASSIFY_SPACE_PROMPT = """你是安全日志分析专家。分析已聚合的空格分隔格式日志（如 Syslog/防火墙日志）。

聚合结果：
{aggregated_json}

请为每个列位置提取以下信息，并结合日志上下文推断列名和类型：
1. field_name: 推断的字段名（如 col_0 可能是 timestamp，col_3 可能是 src_ip）
2. field_type: 值为 ip/port/protocol/time/status/action/severity/category/message/id/number/device/user/url/string
3. aliases: 可能的别名列表
4. position: 列索引（0-based）
5. example_values: 3-5 个样本值
6. total_count: 总出现次数
7. unique_count: 去重后的数量（可估计）

输出 JSON（严格一行）：
{{"fields": [{{"field_name":"...","field_type":"...","aliases":["..."],"position":"...","example_values":["..."],"total_count":N,"unique_count":N}}], "sample_raw_log": "一条原始日志示例", "matched_lines": N, "total_lines": N}}"""

_CLASSIFY_DELIMITED_PROMPT = """你是安全日志分析专家。分析已聚合的分隔符格式日志。

聚合结果：
{aggregated_json}

请为每个列位置提取以下信息，结合日志上下文推断列名和类型：
1. field_name: 推断的字段名
2. field_type: ip/port/protocol/time/status/action/severity/category/message/id/number/device/user/url/string
3. aliases: 可能的别名列表
4. position: 列索引（0-based）
5. example_values: 3-5 个样本值
6. total_count: 总出现次数
7. unique_count: 去重后的数量（可估计）

输出 JSON（严格一行）：
{{"fields": [{{"field_name":"...","field_type":"...","aliases":["..."],"position":"...","example_values":["..."],"total_count":N,"unique_count":N}}], "sample_raw_log": "一条原始日志示例", "matched_lines": N, "total_lines": N}}"""

_CLASSIFY_UNKNOWN_PROMPT = """你是安全日志分析专家。分析以下未知格式的日志，尝试识别其结构并提取特征。

聚合结果：
{aggregated_json}

请为每个可识别的字段提取以下信息：
1. field_name: 推断的字段名
2. field_type: ip/port/protocol/time/status/action/severity/category/message/id/number/device/user/url/string
3. aliases: 可能的别名列表
4. position: 位置描述
5. example_values: 3-5 个样本值
6. total_count: 总出现次数
7. unique_count: 去重后的数量（可估计）

输出 JSON（严格一行）：
{{"fields": [{{"field_name":"...","field_type":"...","aliases":["..."],"position":"...","example_values":["..."],"total_count":N,"unique_count":N}}], "sample_raw_log": "一条原始日志示例", "matched_lines": N, "total_lines": N}}"""

# Prompt 映射表
_CLASSIFY_PROMPTS: dict[str, str] = {
    "json": _CLASSIFY_JSON_PROMPT,
    "kv": _CLASSIFY_KV_PROMPT,
    "space": _CLASSIFY_SPACE_PROMPT,
    "semicolon": _CLASSIFY_DELIMITED_PROMPT,
    "comma": _CLASSIFY_DELIMITED_PROMPT,
    "unknown": _CLASSIFY_UNKNOWN_PROMPT,
}


@tool(
    name="classify_log_features",
    description="对已聚合的日志字段进行分类和特征提取。输入 aggregated_json=聚合结果JSON, format_type=格式类型。返回特征分类结果。",
)
def classify_log_features(aggregated_json: str, format_type: str = "unknown") -> str:
    """
    对聚合后的字段进行 LLM 分类。

    Args:
        aggregated_json: aggregate_by_format 的 JSON 输出
        format_type: 格式类型 (json/kv/space/semicolon/comma/unknown)

    Returns:
        JSON 字符串: {"fields": [...], "sample_raw_log": "...", "matched_lines": N, "total_lines": N}
    """
    try:
        aggregated = json.loads(aggregated_json)
    except json.JSONDecodeError:
        return json.dumps(
            {"fields": [], "error": "聚合结果不是有效 JSON", "total_lines": 0, "matched_lines": 0},
            ensure_ascii=False,
        )

    fields_list = aggregated.get("fields", [])
    total_lines = aggregated.get("total_lines", 0)
    matched_lines = aggregated.get("matched_lines", 0)

    if not fields_list:
        return json.dumps(
            {
                "fields": [],
                "error": "无聚合字段",
                "total_lines": total_lines,
                "matched_lines": matched_lines,
            },
            ensure_ascii=False,
        )

    # 选择对应格式的 prompt
    prompt_template = _CLASSIFY_PROMPTS.get(format_type, _CLASSIFY_UNKNOWN_PROMPT)

    try:
        prompt = prompt_template.format(aggregated_json=aggregated_json)
        response = _call_llm_direct(prompt, temperature=0.1, max_tokens=3000, timeout=60)

        parsed = _try_parse_json(response)
        if parsed is None:
            logger.warning(f"[classify_log_features] LLM 返回非 JSON: {response[:200]}")
            return json.dumps(
                {
                    "fields": [],
                    "error": "LLM 返回非 JSON",
                    "raw_response": response[:500],
                    "total_lines": total_lines,
                    "matched_lines": matched_lines,
                },
                ensure_ascii=False,
            )

        parsed.setdefault("total_lines", total_lines)
        parsed.setdefault("matched_lines", matched_lines)
        parsed.setdefault("sample_raw_log", "")
        parsed.setdefault("fields", [])

        return json.dumps(parsed, ensure_ascii=False)

    except httpx.HTTPStatusError as e:
        logger.error(f"[classify_log_features] API 错误: {e}")
        return json.dumps(
            {
                "fields": [],
                "error": f"LLM API 调用失败: {e.response.status_code}",
                "total_lines": total_lines,
                "matched_lines": matched_lines,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[classify_log_features] 异常: {type(e).__name__}: {e}")
        return json.dumps(
            {"fields": [], "error": str(e), "total_lines": 0, "matched_lines": 0},
            ensure_ascii=False,
        )


# ============================================================================
# Step 4: 替换样例日志 (纯函数)
# ============================================================================


def fill_sample_logs(
    classification: dict, logs_str: str, max_samples: int = 10
) -> dict:
    """
    用分类结果中找到的字段位置信息，填充样例日志。

    Args:
        classification: classify_log_features 的输出
        logs_str: 原始日志字符串
        max_samples: 每种字段类型最多取多少样本日志

    Returns:
        classification 的副本，每个字段增加 "sample_logs" 列表
    """
    fields = classification.get("fields", [])
    if not fields:
        return classification

    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    result = dict(classification)
    result["fields"] = []

    for field_info in fields:
        field_copy = dict(field_info)
        field_copy.setdefault("sample_logs", [])
        result["fields"].append(field_copy)

    return result