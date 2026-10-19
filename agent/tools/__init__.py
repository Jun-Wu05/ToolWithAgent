"""Agent工具包

整合所有业务工具，提供统一的工具接口。跨包适配器只允许使用本门面的公开名，
禁止跨包引用下划线私有实现（Issue #88 工具门面）。
"""

from agent.tools.enum_field_tool import (
    flatten_enum_mappings,
    read_enum_mappings_from_excel,
)
from agent.tools.pipeline.log_format_identifier import identify_log_format
from agent.tools.pipeline.log_classifier import classify_log_features


def identify_log_format_headless(logs_text: str) -> str:
    """日志格式识别纯函数入口（无 @tool 装饰，供 Application 适配器调用）。"""
    from agent.tools.pipeline.log_format_identifier import _do_identify_log_format

    return _do_identify_log_format(logs_text)


def classify_log_features_headless(
    logs_text: str,
    log_format: str,
    format_detail: str,
    feature_field: str,
    format_info_json: str,
    header_end_marker: str,
    feature_field_explicit: bool = False,
) -> str:
    """日志特征分类纯函数入口（无 @tool 装饰，供 Application 适配器调用）。

    ``feature_field_explicit=True`` 表示字段来自用户显式指定，
    分类必须按日志体路径使用该字段，Step 2a 定位器不得改写或改道。
    """
    from agent.tools.pipeline.log_classifier import _do_classify_log_features

    return _do_classify_log_features(
        logs_text,
        log_format,
        format_detail,
        feature_field,
        format_info_json,
        header_end_marker,
        feature_field_explicit=feature_field_explicit,
    )


def fill_log_samples(classification: dict, logs_text: str) -> dict:
    """真实日志样本回填门面，延迟绑定现有 Pipeline 实现。"""
    from agent.tools.pipeline.log_sample_filler import fill_sample_logs

    return fill_sample_logs(classification, logs_text)


def call_llm_direct(*args, **kwargs):
    """直连 LLM 的统一门面（延迟绑定实现，保持测试替身可替换）。"""
    from agent.tools.pipeline.llm_client import _call_llm_direct

    return _call_llm_direct(*args, **kwargs)


__all__ = [
    'flatten_enum_mappings',
    'read_enum_mappings_from_excel',
    'identify_log_format',
    'classify_log_features',
    'identify_log_format_headless',
    'classify_log_features_headless',
    'fill_log_samples',
    'call_llm_direct',
]
