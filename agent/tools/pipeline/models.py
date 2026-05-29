# -*- coding: utf-8 -*-
"""日志解析管道的统一 TypedDict 模型。

管道中所有步骤使用这些标准数据结构，
确保一致性并启用 IDE 类型检查。
"""

from typing import Any, TypedDict


class FormatInfo(TypedDict, total=False):
    """Step 1 的输出 —— 格式识别结果。

    字段:
        format:             JSON, KV, CSV, CEF, LEEF, SYSLOG, PLAINTEXT, UNKNOWN
        format_detail:      LLM 生成的格式描述
        has_header:         body 前是否存在 syslog 风格的头部
        header_end_marker:  头部与 body 之间的分隔字符
        feature_field:      LLM 建议用于分类的字段名
        feature_location:   "header" | "body" | "both" | "unknown"
        confidence:         0.0 ~ 1.0
        reason:             LLM 生成的推理说明
    """

    format: str
    format_detail: str
    delimiter: str
    confidence: float
    kv_connector: str
    kv_separator: str
    has_header: bool
    header_end_marker: str
    has_header_feature: bool
    feature_field: str
    feature_location: str
    reason: str


class AggregationValue(TypedDict):
    """单个聚合值及其计数和样本行。"""

    value: str
    count: int
    samples: list[str]


class AggregationResult(TypedDict):
    """Step 2 的输出 —— 特征值聚合结果。

    字段:
        total_lines:    处理的非空日志行总数
        matched_lines:  找到特征字段的行数
        feature_field:  用于聚合的字段名
        values:         每个值的聚合结果列表
        value_count:    不同值的数量
        top_values:     按计数排列的 Top-N 值（`values` 的子集）
    """

    total_lines: int
    matched_lines: int
    feature_field: str
    values: list[AggregationValue]
    value_count: int
    top_values: list[AggregationValue]


class ClassificationDetail(TypedDict, total=False):
    """单条日志类型分类详情。

    字段:
        logtype:        分类后的日志类型名称
        sample:         匿名化的样本日志行
        real_samples:   原始样本日志行（脱敏前）
        count:          匹配此日志类型的行数
        matched_regex:  匹配此日志类型的正则模式（可选）
        coverage_pct:   占总行数的百分比（可选）
    """

    logtype: str
    sample: str
    real_samples: list[str]
    count: int
    matched_regex: str
    coverage_pct: float


class ClassificationResult(TypedDict, total=False):
    """Step 3 的输出 —— 完整分类结果。

    字段:
        status:                 "SUCCESS" | "UNSUPPORTED" | "ERROR"
        log_format:             格式类型（JSON、KV 等）
        feature_field:          用于分类的字段
        feature_count:          发现的不同日志类型数量
        total_valid_lines:      处理的非空行总数
        covered_lines:          分类覆盖的行数
        classification_details: 日志类型详情列表
        error:                  状态为 "ERROR" 时的错误信息
    """

    status: str
    log_format: str
    feature_field: str
    feature_count: int
    total_valid_lines: int
    covered_lines: int
    classification_details: list[ClassificationDetail]
    error: str