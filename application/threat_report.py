"""从威胁链最终配置构造逐子规则的事件标注报告行。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from agent.shared.event_classify import THREAT_EVENT_NAMES
from application.threat_chain_policy import resolve_threat_mapping_value
from contracts.planner_models import (
    EventAnnotationRow,
    ExecutionReport,
    FieldMappingArtifact,
    THREAT_TYPE_FIELD,
)


FIXED_SOURCE_LABEL = "—（固定值）"
UNRESOLVED_THREAT_LABEL = "⚠️ 无法从样例判定"
NOT_GENERATED_LABEL = "⚠️ 未生成"


def _rule_by_name(config: Any, rule_name: str) -> Mapping[str, Any] | None:
    if not isinstance(config, list):
        return None
    return next(
        (
            rule
            for rule in config
            if isinstance(rule, Mapping) and str(rule.get("name") or "") == rule_name
        ),
        None,
    )


def _threat_binding(rule: Mapping[str, Any]) -> str | None:
    parser = rule.get("parser")
    filters = parser.get("filter", []) if isinstance(parser, Mapping) else []
    for filter_item in filters if isinstance(filters, list) else []:
        fields = filter_item.get("fields") if isinstance(filter_item, Mapping) else None
        if isinstance(fields, Mapping) and THREAT_TYPE_FIELD in fields:
            return str(fields[THREAT_TYPE_FIELD])
    return None


def _normalize_entry(
    rule: Mapping[str, Any], field_name: str
) -> Mapping[str, Any] | None:
    entries = rule.get("normalize", [])
    if not isinstance(entries, list):
        return None
    return next(
        (
            entry
            for entry in entries
            if isinstance(entry, Mapping)
            and (
                str(entry.get("index") or "") == field_name
                or str(entry.get("field") or "") == field_name
            )
        ),
        None,
    )


def _sample_values(entry: Mapping[str, Any] | None) -> tuple[str, ...]:
    raw = entry.get("result") if entry is not None else None
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(value) for value in raw if str(value).strip())


def _reference_field(binding: str) -> str | None:
    if not (binding.startswith("%{") and binding.endswith("}")):
        return None
    source_field = binding[2:-1].strip()
    return source_field or None


def _enrich_threat_row(
    row: EventAnnotationRow, rule: Mapping[str, Any]
) -> EventAnnotationRow:
    binding = _threat_binding(rule)
    if binding is None:
        return row.model_copy(update={"threat_types": (NOT_GENERATED_LABEL,)})

    source_field = _reference_field(binding)
    if source_field is None:
        return row.model_copy(
            update={
                "threat_source_field": FIXED_SOURCE_LABEL,
                "threat_types": (binding or "其他",),
            }
        )

    samples = _sample_values(_normalize_entry(rule, source_field))
    target = _normalize_entry(rule, THREAT_TYPE_FIELD)
    mappings = target.get("mappings", []) if target is not None else []
    mapping_rows = mappings if isinstance(mappings, list) else []
    resolved = tuple(
        dict.fromkeys(
            mapped
            for sample in samples
            if (mapped := resolve_threat_mapping_value(sample, mapping_rows))
        )
    )
    return row.model_copy(
        update={
            "threat_source_field": source_field,
            "threat_types": resolved or (UNRESOLVED_THREAT_LABEL,),
        }
    )


def build_threat_report_rows(
    annotations: Iterable[EventAnnotationRow],
    final_config: Any,
    *,
    chain_succeeded: bool,
) -> tuple[EventAnnotationRow, ...]:
    """用最终配置刷新标注行；普通事件不带威胁列，未知/失败显式标记。"""
    rows: list[EventAnnotationRow] = []
    for row in annotations:
        if row.status == "uncertain":
            rows.append(row.model_copy(update={"threat_types": (NOT_GENERATED_LABEL,)}))
            continue
        if row.event_name not in THREAT_EVENT_NAMES:
            rows.append(
                row.model_copy(update={"threat_source_field": "", "threat_types": ()})
            )
            continue
        rule = _rule_by_name(final_config, row.rule_name)
        if not chain_succeeded or rule is None:
            rows.append(row.model_copy(update={"threat_types": (NOT_GENERATED_LABEL,)}))
            continue
        rows.append(_enrich_threat_row(row, rule))
    return tuple(rows)


def refresh_report_event_annotations(
    report: ExecutionReport,
    final_config: Any,
    *,
    chain_succeeded: bool,
) -> ExecutionReport:
    """替换报告中的字段映射标注行，其他结果与 artifact 内容保持不变。"""
    refreshed_results = []
    for result in report.results:
        artifact = result.artifact
        if not isinstance(artifact, FieldMappingArtifact):
            refreshed_results.append(result)
            continue
        refreshed_artifact = artifact.model_copy(
            update={
                "event_annotations": build_threat_report_rows(
                    artifact.event_annotations,
                    final_config,
                    chain_succeeded=chain_succeeded,
                )
            }
        )
        refreshed_results.append(result.model_copy(update={"artifact": refreshed_artifact}))
    return report.model_copy(update={"results": tuple(refreshed_results)})


__all__ = [
    "FIXED_SOURCE_LABEL",
    "NOT_GENERATED_LABEL",
    "UNRESOLVED_THREAT_LABEL",
    "build_threat_report_rows",
    "refresh_report_event_annotations",
]
