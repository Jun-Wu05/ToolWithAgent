"""Prompt 资源及其归属于包内的加载策略。"""

from pathlib import Path

from agent.core.standard_field_catalog import get_standard_field_catalog


__all__ = [
    "get_prompts_dir",
    "load_clarification_prompt",
    "load_enum_extract_prompt",
    "load_enum_field_prompt",
    "load_enum_value_review_prompt",
    "load_event_classify_prompt",
    "load_field_strong_prompt",
    "load_field_weak_prompt",
    "load_kv_feature_identifier_prompt",
    "load_log_classify_feature_prompt",
    "load_log_feature_locate_prompt",
    "load_log_format_identify_prompt",
    "load_log_header_classify_prompt",
    "load_log_header_regex_identifier_prompt",
    "load_planner_prompt",
    "load_standard_fields",
    "load_threat_type_prompt",
]


def get_prompts_dir() -> str:
    """获取 prompts 目录"""
    return str(Path(__file__).parent)


def _load_md_or_fail(filename: str, description: str) -> str:
    """加载 .md 提示词文件，缺失时直接报错终止"""
    prompt_path = Path(__file__).parent / filename

    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')

    raise FileNotFoundError(f"提示词文件丢失: {filename} ({description})，请检查 agent/prompts/ 目录")


def _load_optional_md(filename: str) -> str:
    """加载日志 Pipeline 提示词；缺失时保持历史空字符串策略。"""
    prompt_path = Path(__file__).parent / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return ""


def load_log_format_identify_prompt() -> str:
    """加载日志格式识别提示词。"""
    return _load_optional_md("log_format_identify.md")


def load_clarification_prompt() -> str:
    """加载升级追问生成指令。"""
    return _load_md_or_fail("clarification.md", "升级追问生成")


def load_log_classify_feature_prompt() -> str:
    """加载日志特征分类提示词。"""
    return _load_optional_md("log_classify_feature.md")


def load_log_header_classify_prompt() -> str:
    """加载日志头分类提示词。"""
    return _load_optional_md("log_header_classify.md")


def load_log_feature_locate_prompt() -> str:
    """加载日志分类特征字段定位提示词。"""
    return _load_optional_md("log_feature_locate.md")


def load_kv_feature_identifier_prompt() -> str:
    """加载 KV 特征正则生成提示词。"""
    return _load_optional_md("kv_feature_identifier.md")


def load_log_header_regex_identifier_prompt() -> str:
    """加载日志头类型提取正则生成提示词（#190）。"""
    return _load_optional_md("log_header_regex_identifier.md")


def load_field_weak_prompt() -> str:
    """加载弱匹配标准字段映射提示词"""
    return _load_md_or_fail("field_weak.md", "字段映射弱匹配")


def load_field_strong_prompt() -> str:
    """加载强匹配标准字段映射提示词"""
    return _load_md_or_fail("field_strong.md", "字段映射强匹配")


def load_threat_type_prompt() -> str:
    """加载威胁类型标准化提示词"""
    return _load_md_or_fail("threat_type.md", "威胁类型标准化")


def load_enum_field_prompt() -> str:
    """加载普通字段枚举处理提示词"""
    return _load_md_or_fail("enum_field.md", "枚举字段处理")


def load_enum_value_review_prompt() -> str:
    """加载标准枚举值第二阶段归类提示词（#189）"""
    return _load_md_or_fail("enum_value_review.md", "标准枚举值归类")


def load_standard_fields() -> str:
    """加载标准字段表（全量返回）"""
    try:
        return get_standard_field_catalog().standard_fields_text
    except (FileNotFoundError, OSError):
        return "标准字段表加载失败"


def load_enum_extract_prompt() -> str:
    """加载日志枚举提取提示词"""
    return _load_md_or_fail("enum_extract.md", "日志枚举提取")


def load_planner_prompt() -> str:
    """加载 Planner 指令；保留 ``Path.read_text`` 的原生缺失异常。"""
    return (Path(__file__).parent / "planner.md").read_text(encoding="utf-8")


def load_event_classify_prompt() -> str:
    """加载事件名称判定知识；缺失时保留历史错误消息。"""
    prompt_path = Path(__file__).parent / "event_classify.md"
    if not prompt_path.is_file():
        raise FileNotFoundError(f"事件名称判定知识文件不存在: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
