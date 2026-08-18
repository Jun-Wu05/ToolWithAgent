"""Agent工具包

整合所有业务工具，提供统一的工具接口。web 层只允许使用本门面的公开名，
禁止跨包引用下划线私有实现（Issue #88 工具门面）。
"""

from agent.tools.standard_mapper import field_mapping_tool
from agent.tools.enum_field_tool import enum_field_tool
from agent.tools.logs_enum_tool import (
    extract_enum_from_logs,
    extract_enum_with_regex,
)
from agent.tools.pipeline.log_format_identifier import identify_log_format
from agent.tools.pipeline.log_classifier import classify_log_features


def identify_log_format_headless(logs_text: str) -> str:
    """日志格式识别纯函数入口（无 @tool 装饰，供 web 执行适配器调用）。"""
    from agent.tools.pipeline.log_format_identifier import _do_identify_log_format

    return _do_identify_log_format(logs_text)


def classify_log_features_headless(
    logs_text: str,
    log_format: str,
    format_detail: str,
    feature_field: str,
    format_info_json: str,
    header_end_marker: str,
) -> str:
    """日志特征分类纯函数入口（无 @tool 装饰，供 web 执行适配器调用）。"""
    from agent.tools.pipeline.log_classifier import _do_classify_log_features

    return _do_classify_log_features(
        logs_text,
        log_format,
        format_detail,
        feature_field,
        format_info_json,
        header_end_marker,
    )


def call_llm_direct(*args, **kwargs):
    """直连 LLM 的统一门面（延迟绑定实现，保持测试替身可替换）。"""
    from agent.tools.pipeline.llm_client import _call_llm_direct

    return _call_llm_direct(*args, **kwargs)


def load_object_mapping(excel_path: str) -> dict:
    """系统属性对象映射加载门面（延迟绑定实现，保持测试替身可替换）。"""
    from agent.tools.standard_mapper import _load_object_mapping

    return _load_object_mapping(excel_path)


__all__ = [
    'field_mapping_tool',
    'enum_field_tool',
    'extract_enum_from_logs',
    'extract_enum_with_regex',
    'identify_log_format',
    'classify_log_features',
    'identify_log_format_headless',
    'classify_log_features_headless',
    'call_llm_direct',
    'load_object_mapping',
]
