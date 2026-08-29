"""值映射填充适配器共享的固定字段解绑实现。"""

from __future__ import annotations

from typing import Any

from agent.shared.logger import get_logger
from agent.shared.mapping_utils import unbind_fixed_fields
from agent.tools.rule_generator.field_mapping import MAPPING_EXCLUDED_STANDARD_FIELDS


logger = get_logger("execution_adapters")


def unbind_fixed_field_bindings(
    config: Any, target_fields: tuple[str, ...]
) -> tuple[Any, str]:
    """固定字段的绑定值会让值映射失效，因此填充前先解除绑定。"""
    fixed_hit = set(target_fields) & MAPPING_EXCLUDED_STANDARD_FIELDS
    if not fixed_hit:
        return config, ""
    updated, unbound = unbind_fixed_fields(config, target_fields)
    if not unbound:
        return config, ""
    note = (
        f"；已解除 {len(unbound)} 条规则的固定值绑定"
        f"（{'、'.join(sorted(fixed_hit))} 改由值映射控制）"
    )
    logger.info(
        "[FILL_UNBIND] 填充即解绑: target_fields=%s unbound_rules=%s",
        sorted(fixed_hit),
        len(unbound),
    )
    return updated, note


__all__ = ["unbind_fixed_field_bindings"]
