"""标准字段映射条目的合法性校验与规范化（#177 白名单降级策略的唯一实现）。

历史说明：本模块曾承载 Agno Tool 版字段映射检索栈（field_mapping_tool /
generate_mapping_table_tool / query_field_candidates / lookup_standard_field_tool
及配套私有函数）；生产路径自 #146 起改走 application 适配器 + field_retriever +
rule_generator，旧栈已删除（issue #327）。现仅保留 `_validate_and_correct_mapping`
——仍被 tests/test_mapping_blocklist.py 与 tests/test_standard_field_entity_validation.py
消费；它留在本模块而不迁入 rule_generator，是因其依赖的
MAPPING_EXCLUDED_STANDARD_FIELDS / resolve_standard_field 自该包导入且迁移会与
在途字段映射工作（#266/#267）的改动面相交。
"""
from agent.shared.logger import get_logger

logger = get_logger("standard_mapper")


def _validate_and_correct_mapping(mapping: dict) -> dict:
    """
    校验单条映射的「系统属性名称」并规范化为标准字段目录规范名称（#177）。

    - 若"未匹配"则跳过校验（合法状态）
    - 若匹配成功但名称在映射目标黑名单（系统固定字段）中 → 强制改为"未匹配"并记录警告
    - 若名称可经目录唯一规范化（前后空白/英文字段名/变体）→ 改写为目录规范系统属性名称
    - 若名称不在目录中 → 强制改为"未匹配"并记录警告

    Returns:
        校验/修正后的映射 dict（可能是原始引用或新 dict）
    """
    from agent.tools.rule_generator.field_mapping import (
        MAPPING_EXCLUDED_STANDARD_FIELDS,
        resolve_standard_field,
    )

    system_property = mapping.get("系统属性名称", "")
    match_status = mapping.get("匹配状态", "")

    # "未匹配" 是合法终态，无需校验
    if system_property == "未匹配":
        return mapping

    # 系统固定字段（事件名称/事件级别/日志类型/威胁类型）由固定机制独占，不允许映射占用（issue #125/#173）
    if system_property in MAPPING_EXCLUDED_STANDARD_FIELDS:
        logger.warning(
            f"[VALIDATOR] 系统固定字段 → 强制降级为未匹配: "
            f"原始字段={mapping.get('原始字段名', '?')}, 目标='{system_property}'"
        )
        return {
            "原始字段名": mapping.get("原始字段名", ""),
            "系统属性名称": "未匹配",
            "匹配状态": "未匹配",
            "_校正原因": (
                f"'{system_property}' 是系统固定字段（由事件名称标注等机制独占），"
                f"不允许字段映射占用"
            ),
        }

    record = resolve_standard_field(system_property)
    if record is None:
        logger.warning(
            f"[VALIDATOR] 非法字段名 → 强制降级为未匹配: "
            f"原始字段={mapping.get('原始字段名', '?')}, "
            f"非法名称='{system_property}'"
        )
        # 创建新 dict 避免修改调用方的原始数据
        return {
            "原始字段名": mapping.get("原始字段名", ""),
            "系统属性名称": "未匹配",
            "匹配状态": "未匹配",
            "_校正原因": f"LLM 输出了不在标准字段表中的名称 '{system_property}'",
        }

    if record.system_property_name != system_property:
        logger.info(
            f"[VALIDATOR] 变体名称规范化: '{system_property}' -> "
            f"'{record.system_property_name}'"
        )
        return {
            "原始字段名": mapping.get("原始字段名", ""),
            "系统属性名称": record.system_property_name,
            "匹配状态": match_status or "匹配成功",
            "_校正原因": (
                f"'{system_property}' 已规范化为标准字段表规范名称 "
                f"'{record.system_property_name}'"
            ),
        }

    return mapping
