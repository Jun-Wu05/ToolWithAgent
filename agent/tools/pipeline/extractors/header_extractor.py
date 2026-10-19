# -*- coding: utf-8 -*-
"""Path A 专用的日志头特征提取器（syslog 头部分类）。"""

from __future__ import annotations

import re as _re
from collections import defaultdict
from typing import Any, Callable

from agent.tools.pipeline.extractors.base import ValueExtractor

# 头部令牌脱敏正则（IP、时间戳、UUID 等）
_HEADER_DESENSITIZE_RE = _re.compile(
    r"<\d+>|"
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?|"
    r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}|"
    r"\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}|"
    r"\d{1,3}(\.\d{1,3}){3}|"
    r"([0-9a-fA-F]{1,4}:){1,7}[0-9a-fA-F]{1,4}|::|"
    r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})|"
    r"[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}|"
    r"[a-zA-Z0-9]{15,}|"
    r"\b\d+[kKmMgGtTbB%]+\b|"  # 数字+单位后缀（250k, 50GB, 98%）
    r"(?<!/)\b\d+\b(?!/)|"
    r"host|server|pid|ppid|uid|gid|sessionid|messageid",
    _re.IGNORECASE,
)


def extract_header(line: str, format_type: str = "json", kv_delimit: str = "=") -> str:
    """提取日志行的头部部分（JSON/数组/KV 分隔符之前的文本）。

    Args:
        line: 单条日志行。
        format_type: 日志格式（"json" 或 "kv"）。
        kv_delimit: KV 格式的键值分隔符（如 "=" 或 ":"）。

    Returns:
        头部文本，未找到分隔符时返回整行。
    """
    # 1. JSON 分割：找 { 或 [
    json_start = line.find("{")
    if json_start == -1:
        json_start = line.find("[")
    if json_start > 0:
        return line[:json_start].strip()

    # 2. KV 分割：用 kv_delimit 字符定位第一个 KV 对
    # 支持 -前缀、(数字)后缀的字段名（如 -Slot=、SrcZoneName(1025)=）
    # 大小写无关（#190：生产侧 format_type 为大写 "KV"）
    if format_type and format_type.lower() == "kv" and kv_delimit:
        # 匹配：空格/行首 + 字段名(含.-前缀和(数字)后缀) + kv_delimit
        pattern = rf'(?:^|\s)[\w.-]+(?:\(\d+\))?\s*{_re.escape(kv_delimit)}'
        match = _re.search(pattern, line)
        if match:
            # 如果 match 在行首，说明无 header
            return line[:match.start()].strip() if match.start() > 0 else ""

    return line.strip()


def desensitize_header(header: str) -> str:
    """将敏感令牌（IP、时间戳、UUID 等）替换为 ``"1"``。

    Args:
        header: 原始头部文本。

    Returns:
        脱敏后的头部字符串。
    """
    desensitized = _HEADER_DESENSITIZE_RE.sub("1", header)
    desensitized = _re.sub(r"\s+", " ", desensitized).strip()
    return desensitized


def aggregate_headers(
    logs_str: str,
    format_type: str = "json",
    kv_delimit: str = "=",
    max_clusters: int = 50,
    max_header_len: int = 3000,
    header_fn: Callable[[str], str] | None = None,
) -> dict:
    """提取、脱敏并聚类日志头部。

    Args:
        logs_str:       原始多行日志字符串。
        format_type:    日志格式（"json" 或 "kv"）。
        kv_delimit:     KV 格式的键值分隔符。
        max_clusters:   最大唯一头部聚类数。
        max_header_len: 每条头部样本的最大字符数。
        header_fn:      可选的自定义单行 header 切分函数，``None`` 时用
                        ``extract_header`` 按分隔符切分。调用方持有更可靠的
                        边界依据（如已验证 body 正则的捕获起点，#294）时注入。

    Returns:
        {
            "clusters": [
                {"log_header": "<脱敏后的头部文本>", "count": int},
                ...
            ],
            "total_lines": int,
        }
    """
    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    total_lines = len(lines)

    cluster_map: dict[str, int] = defaultdict(int)
    header_samples: dict[str, str] = {}
    # CHANGED: 新增 raw_samples，存储每个 cluster 的原始未脱敏日志行
    raw_samples: dict[str, str] = {}

    for line in lines:
        if len(cluster_map) >= max_clusters:
            break

        header = header_fn(line) if header_fn else extract_header(line, format_type, kv_delimit)
        if not header:
            continue

        desensitized = desensitize_header(header)
        if not desensitized:
            continue

        cluster_map[desensitized] += 1
        if desensitized not in header_samples:
            sample = desensitized[:max_header_len]
            if len(desensitized) > max_header_len:
                sample += "...日志过长已截断"
            header_samples[desensitized] = sample
        # CHANGED: 存储原始未脱敏日志行，供下游分层采样使用
        if desensitized not in raw_samples:
            raw_samples[desensitized] = line[:max_header_len]

    sorted_clusters = sorted(cluster_map.items(), key=lambda x: x[1], reverse=True)
    clusters = [
        {"log_header": header_samples[header], "count": count,
         "raw_sample": raw_samples.get(header, "")}
        for header, count in sorted_clusters
    ]

    return {"clusters": clusters, "total_lines": total_lines}


class HeaderExtractor(ValueExtractor):
    """syslog 风格日志头特征提取器（Path A）。

    专为分类特征位于日志头部（JSON body 之前）的场景设计。
    提供单行提取和批量聚合两种能力。
    """

    def extract_value(self, line: str, feature_field: str) -> Any:
        """从单行中提取脱敏后的头部值。

        ``feature_field`` 参数在头部提取时被忽略 ——
        "值"始终是脱敏后的头部文本。

        Args:
            line:           单条日志行。
            feature_field:  被忽略；保留以兼容接口。

        Returns:
            脱敏后的头部字符串，或 None。
        """
        header = extract_header(line)
        if not header:
            return None
        desensitized = desensitize_header(header)
        return desensitized or None

    def extract_and_aggregate(
        self,
        logs_str: str,
        feature_field: str,
        max_lines: int | None = None,
    ) -> dict:
        """聚合头部聚类（委托给 :func:`aggregate_headers`）。

        Args:
            logs_str:      原始多行日志字符串。
            feature_field: 被忽略；保留以兼容接口。
            max_lines:     被忽略（头部聚合使用 max_clusters）。

        Returns:
            包含 ``clusters`` 和 ``total_lines`` 的字典。
        """
        return aggregate_headers(logs_str)