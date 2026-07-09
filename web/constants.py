"""
Web 层共享常量 — 消除散落在多处的魔法字符串

集中定义列名等重复 literal，供各模块 import 引用。
注：EXCLUDED_FIELD_INDICES 真相源在 agent.tools.rule_generator.field_mapping
（agent 层不应依赖 web 层），web 层从那里 import。
"""

# Excel 数据表格中可能出现的"原始日志"列名变体（用于检测并预提取日志行）
ORIGINAL_LOG_COLUMN_KEYWORD = "原始日志"
