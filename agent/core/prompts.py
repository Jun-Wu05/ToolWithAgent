"""兼容入口：日志 Pipeline Prompt 加载实现已归入 Prompt 包。"""

from agent.prompts import (
    load_kv_feature_identifier_prompt,
    load_log_classify_feature_prompt,
    load_log_feature_locate_prompt,
    load_log_format_identify_prompt,
    load_log_header_classify_prompt,
)

__all__ = [
    "load_kv_feature_identifier_prompt",
    "load_log_classify_feature_prompt",
    "load_log_feature_locate_prompt",
    "load_log_format_identify_prompt",
    "load_log_header_classify_prompt",
]
