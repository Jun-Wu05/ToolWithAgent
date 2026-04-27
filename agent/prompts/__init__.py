"""
Prompts 模块
"""
import os
from pathlib import Path


def get_prompts_dir() -> str:
    """获取 prompts 目录"""
    return str(Path(__file__).parent)


def _load_md_or_fail(filename: str, description: str) -> str:
    """加载 .md 提示词文件，缺失时直接报错终止"""
    prompt_path = Path(__file__).parent / filename

    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')

    raise FileNotFoundError(f"提示词文件丢失: {filename} ({description})，请检查 agent/prompts/ 目录")


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


def load_router_prompt() -> str:
    """加载 Team Router 路由指令提示词"""
    return _load_md_or_fail("router.md", "Team 路由指令")


def load_standard_fields() -> str:
    """加载标准字段表（全量返回）"""
    data_path = Path(__file__).parent.parent / "data" / "标准字段.txt"
    
    if data_path.exists():
        content = data_path.read_text(encoding='utf-8')
        return content
    
    return "标准字段表加载失败"
