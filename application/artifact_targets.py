"""解析可引用会话产物在配置 normalize 中的标准目标字段。"""

from __future__ import annotations

from typing import Any

from agent.shared.mapping_utils import iter_normalize_entries


def resolve_standard_target(config: Any, source_field: str) -> str | None:
    """从 normalize.index 到 normalize.field 解析唯一、非空的标准目标字段。

    遍历自 agent.shared.mapping_utils.iter_normalize_entries 收口（#330）：
    与 apply_fill_to_config / _has_threat_type_entry 共用同一遍历实现
    （require_index=False 的固定目标判定语义，考察全部 dict 条目），
    匹配规则不再与填充链路人工保持同步。
    """
    targets: set[str] = set()
    for _path, _position, _owner, entry in iter_normalize_entries(
        config, require_index=False
    ):
        index_value = str(entry.get("index", "")).strip()
        field_value = str(entry.get("field", "")).strip()
        if field_value and (index_value == source_field or field_value == source_field):
            targets.add(field_value)
    return next(iter(targets)) if len(targets) == 1 else None
