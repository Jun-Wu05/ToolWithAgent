"""
Prompts 模块
"""
import os
from pathlib import Path


def get_prompts_dir() -> str:
    """获取 prompts 目录"""
    return str(Path(__file__).parent)


def load_field_weak_prompt() -> str:
    """
    加载弱匹配标准字段映射提示词
    复制自 auto/phase2/标准字段.md
    """
    prompt_path = Path(__file__).parent / "field_weak.md"
    
    # 如果文件不存在，尝试从原始位置加载
    if not prompt_path.exists():
        original_path = Path(__file__).parent.parent.parent / "auto" / "phase2" / "标准字段.md"
        if original_path.exists():
            prompt_path = original_path
    
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    
    return _get_default_field_prompt()


def load_field_strong_prompt() -> str:
    """
    加载强匹配标准字段映射提示词
    复制自 auto/phase2/提示词-强匹配.md
    """
    prompt_path = Path(__file__).parent / "field_strong.md"
    
    # 如果文件不存在，尝试从原始位置加载
    if not prompt_path.exists():
        original_path = Path(__file__).parent.parent.parent / "auto" / "phase2" / "提示词-强匹配.md"
        if original_path.exists():
            prompt_path = original_path
    
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    
    return _get_default_strong_prompt()


def load_threat_type_prompt() -> str:
    """
    加载威胁类型标准化提示词
    复制自 auto/phase2/威胁类型.md
    """
    prompt_path = Path(__file__).parent / "threat_type.md"
    
    # 如果文件不存在，尝试从原始位置加载
    if not prompt_path.exists():
        original_path = Path(__file__).parent.parent.parent / "auto" / "phase2" / "威胁类型.md"
        if original_path.exists():
            prompt_path = original_path
    
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    
    return _get_default_threat_prompt()


def load_enum_field_prompt() -> str:
    """
    加载普通字段枚举处理提示词
    """
    prompt_path = Path(__file__).parent / "enum_field.md"
    
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    
    return _get_default_enum_field_prompt()


def _get_default_field_prompt() -> str:
    """默认的字段映射提示词"""
    return """
## 角色
你是网络安全日志标准化专家，负责将原始日志字段映射到标准系统属性。

## 任务
根据以下输入完成字段映射：1. 原始日志 JSON；2. 提取的字段列表；3. 标准字段表。输出严格对齐的标准字段映射表。

## 目标与边界
1. 只能使用标准字段表中的中文系统属性名称作为输出；否则输出"无匹配"。
2. 禁止自造字段名、禁止翻译字段名。
3. 检索范围覆盖全部对象与分区，但必须优先利用"对象"列缩小范围。

## 输出要求
1. 只输出最终 Markdown 表格，不输出解释、分析、过程或备注。
2. 表头固定为：| 原始字段名 | 系统属性名称 | 匹配状态/说明 |
3. 匹配成功时说明固定为：匹配成功，字段语义与系统属性定义一致
4. 无匹配时说明固定为：未在标准表中找到可唯一确定且值域一致的系统属性名称
"""


def _get_default_strong_prompt() -> str:
    """默认的强匹配提示词"""
    return """
## 角色
你是网络安全日志标准化专家，负责将原始日志字段映射到标准系统属性。

## 硬约束
1. 匹配成功必须同时满足三一致：字段名语义一致、字段值/值域一致、标准字段描述一致；任一不满足即"无匹配"。
2. 禁止仅因词面相近而匹配。
3. 对象无法判断时，必须输出"无匹配"。

## 输出要求
只输出 Markdown 表格：| 原始字段名 | 系统属性名称 | 匹配状态/说明 |
"""


def _get_default_threat_prompt() -> str:
    """默认的威胁类型提示词"""
    return """
You are a threat alert to standard classification mapper. Given the reference item list, output a mapping table according to the following rules.

## Output Format
Only output one Markdown table with three columns: mappingType, orgValue, mappingValue
Do not output any explanations, comments, or extra text

## Rules
1. mappingType is always REGULAR
2. orgValue format is (?i).*keyword.*, where the keyword is extracted from the alert as the core threat term
3. mappingValue selects the best match from the reference item list
4. Matching priority: exact match > semantic match > use "其他"
"""


def _get_default_enum_field_prompt() -> str:
    """默认的枚举字段处理提示词"""
    return """
## 角色
你是网络安全设备配置规则枚举字段处理专家。

## 任务
根据用户选择的枚举字段，生成字段值到标准值的映射表。

## 输入
1. 目标枚举字段名称
2. 字段的原始值列表
3. 标准值参考列表（如有）

## 输出要求
1. 只输出 Markdown 格式的映射表
2. 表头固定为：| mappingType | orgValue | mappingValue |
3. mappingType 固定为 REGULAR
4. mappingValue 应尽可能匹配标准值

## 示例
| mappingType | orgValue | mappingValue |
|-------------|----------|--------------|
| REGULAR     | sql注入  | SQL注入攻击  |
| REGULAR     | xss攻击  | XSS攻击      |
"""


def load_standard_fields() -> str:
    """加载标准字段表（全量返回）"""
    # 优先从 agent/data/ 加载
    data_path = Path(__file__).parent.parent / "data" / "标准字段.txt"
    if not data_path.exists():
        # 从 auto/phase2/data/ 加载
        data_path = Path(__file__).parent.parent.parent / "auto" / "phase2" / "data" / "标准字段.txt"
    
    if data_path.exists():
        content = data_path.read_text(encoding='utf-8')
        return content
    
    return "标准字段表加载失败"
