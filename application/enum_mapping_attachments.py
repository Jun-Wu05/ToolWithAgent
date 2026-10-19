"""枚举映射附件提交：按 Sheet 原子合并并维护配置过期状态。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agent.tools import flatten_enum_mappings
from application.session_state import SessionState


def commit_enum_mapping_attachment(
    session: SessionState,
    source_path: str,
    uploaded_sheets: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """提交完整解析的工作簿；不同 Sheet 累积，同名 Sheet 完整替换。"""
    existing_sheets = session.enum_mapping_sheets or {}
    merged_sheets = {
        name: [dict(row) for row in rows] for name, rows in existing_sheets.items()
    }
    merged_sheets.update(
        {name: [dict(row) for row in rows] for name, rows in uploaded_sheets.items()}
    )
    preview = flatten_enum_mappings(merged_sheets)
    contributions = session.enum_fill_contributions or {}
    stale_refs = set(session.stale_enum_config_refs or set())
    stale_refs.update(contributions)
    pending_refills = {
        config_ref: set(sheet_names)
        for config_ref, sheet_names in (
            session.enum_pending_refills or {}
        ).items()
    }
    for config_ref in contributions:
        pending_refills.setdefault(config_ref, set()).update(uploaded_sheets)
    session.enum_mapping_sheets = merged_sheets
    session.enum_preview = preview
    session.enum_excel_path = source_path
    session.stale_enum_config_refs = stale_refs
    session.enum_pending_refills = pending_refills
    return preview


__all__ = ["commit_enum_mapping_attachment"]
