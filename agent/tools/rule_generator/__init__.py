"""规则生成包：根据日志分类结果生成入口规则和子规则（纯函数，不依赖 Chainlit）。

本包由原单文件 ``rule_generator.py`` 拆分而来，拆分为 6 个职责单一的子模块：
- templates:  规则模板常量与深拷贝访问器
- utils:      通用工具（时间戳/UUID/值转换/转义/KV解析器）
- filters:    Filter 构建（addFields/redirect/conditionMatch）
- normalize:  Normalize 条目构建
- field_mapping: 标准字段映射
- core:       核心生成逻辑

向后兼容：本 ``__init__`` 重导出所有原有公共接口，
``from agent.tools.rule_generator import xxx`` 的导入方式保持不变，
调用方（如 web/action_callbacks.py）无需任何修改。

Typical usage:
    from agent.tools.rule_generator import generate_rules, rules_to_base64_text
    rules = generate_rules(classification, mode="both")
    txt = rules_to_base64_text(rules["rules"])
"""

from .core import (
    generate_rules,
    generate_entry_rule,
    generate_sub_rule,
    generate_sub_rules,
    rules_to_base64_text,
)
from .field_mapping import (
    extract_sub_rule_mapping_info,
    apply_field_mapping_to_sub_rules,
)

__all__ = [
    # 核心生成
    "generate_rules",
    "generate_entry_rule",
    "generate_sub_rule",
    "generate_sub_rules",
    "rules_to_base64_text",
    # 标准字段映射
    "extract_sub_rule_mapping_info",
    "apply_field_mapping_to_sub_rules",
]