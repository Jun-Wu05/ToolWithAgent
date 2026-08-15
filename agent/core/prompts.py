"""日志解析 Pipeline 的 Prompt 加载器。

历史遗留的关键词路由系统提示词（load_system_prompt）与字段映射/威胁/枚举
的重复加载器已随统一 Planner 架构（ADR-0005）删除；存活副本位于
``agent/prompts/__init__.py``（team.py 与 standard_mapper 使用）。
本模块只保留日志解析 Pipeline 各步骤实际引用的加载器。
"""

from pathlib import Path


def load_log_format_identify_prompt() -> str:
    """加载日志格式识别提示词"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "log_format_identify.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""


def load_log_classify_feature_prompt() -> str:
    """加载日志特征分类提示词"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "log_classify_feature.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""


def load_log_header_classify_prompt() -> str:
    """加载日志头分类专用提示词（Path A）"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "log_header_classify.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""


def load_log_feature_locate_prompt() -> str:
    """加载特征定位提示词（Step 2a）"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "log_feature_locate.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""


def load_kv_feature_identifier_prompt() -> str:
    """加载 KV feature_identifier 生成提示词（日志头+KV 格式）"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "kv_feature_identifier.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""
