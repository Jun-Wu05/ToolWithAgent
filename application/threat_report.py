"""从威胁链最终配置构造逐子规则的事件标注报告行。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from agent.shared.event_classify import OPERATION_TYPE_FIELD, THREAT_EVENT_NAMES
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


def _field_binding(rule: Mapping[str, Any], field_name: str) -> str | None:
    parser = rule.get("parser")
    filters = parser.get("filter", []) if isinstance(parser, Mapping) else []
    for filter_item in filters if isinstance(filters, list) else []:
        fields = filter_item.get("fields") if isinstance(filter_item, Mapping) else None
        if isinstance(fields, Mapping) and field_name in fields:
            return str(fields[field_name]) if fields[field_name] is not None else None
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


def _rule_sample_values(
    rule: Mapping[str, Any], source_field: str
) -> tuple[str, ...]:
    """normalize 无样例结果时，按规则自身 KV 解析参数读取 sample。"""
    parser = rule.get("parser")
    if not isinstance(parser, Mapping) or parser.get("name") != "delimitWithKeyMap":
        return ()
    sample = rule.get("sample")
    lines = sample if isinstance(sample, list) else str(sample or "").splitlines()
    if not lines:
        return ()
    field_delimit = {r"\s": "space", r"\t": "\t"}.get(
        str(parser.get("delimit") or ""), str(parser.get("delimit") or "")
    )
    kv_delimit = str(parser.get("tab") or "")
    if not field_delimit or not kv_delimit:
        return ()
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    try:
        extractor = KvExtractor(
            field_delimit=field_delimit,
            kv_delimit=kv_delimit,
        )
        return tuple(
            dict.fromkeys(
                str(value)
                for line in lines
                if (value := extractor.extract_value(str(line), source_field)) is not None
                and str(value).strip()
            )
        )
    except (TypeError, ValueError):
        return ()


def _reference_field(binding: str) -> str | None:
    if not (binding.startswith("%{") and binding.endswith("}")):
        return None
    source_field = binding[2:-1].strip()
    return source_field or None


def _resolve_type_binding(
    rule: Mapping[str, Any], field_name: str
) -> tuple[str, tuple[str, ...]]:
    """按最终配置解析固定值或字段引用，不根据字段存在推断绑定。"""
    binding = _field_binding(rule, field_name)
    target = _normalize_entry(rule, field_name)
    if binding is None and field_name == OPERATION_TYPE_FIELD and target is not None:
        value = target.get("value")
        if value is not None and str(value).strip():
            binding = str(value)
    if binding is None or (field_name == OPERATION_TYPE_FIELD and not binding.strip()):
        return "", (NOT_GENERATED_LABEL,)

    source_field = _reference_field(binding)
    if source_field is None:
        return FIXED_SOURCE_LABEL, (binding or "其他",)

    samples = _sample_values(_normalize_entry(rule, source_field)) or _rule_sample_values(
        rule, source_field
    )
    mappings = target.get("mappings", []) if target is not None else []
    mapping_rows = mappings if isinstance(mappings, list) else []
    if field_name == OPERATION_TYPE_FIELD and not mapping_rows:
        resolved = tuple(dict.fromkeys(samples))
    else:
        resolved = tuple(dict.fromkeys(
            mapped for sample in samples
            if (mapped := resolve_threat_mapping_value(sample, mapping_rows))
        ))
    return source_field, resolved or (UNRESOLVED_THREAT_LABEL,)


def _enrich_threat_row(
    row: EventAnnotationRow, rule: Mapping[str, Any]
) -> EventAnnotationRow:
    source, values = _resolve_type_binding(rule, THREAT_TYPE_FIELD)
    return row.model_copy(update={"threat_source_field": source, "threat_types": values})


def event_type_determination(
    row: EventAnnotationRow, final_config: Any
) -> tuple[str, tuple[str, ...]]:
    """本人结果视图的共用类型来源/值；威胁结果保留实际链路结论。"""
    if row.status == "uncertain" or row.event_name in THREAT_EVENT_NAMES:
        return row.threat_source_field, row.threat_types or (NOT_GENERATED_LABEL,)
    rule = _rule_by_name(final_config, row.rule_name)
    if rule is None:
        return "", (NOT_GENERATED_LABEL,)
    return _resolve_type_binding(rule, OPERATION_TYPE_FIELD)


def build_threat_report_rows(
    annotations: Iterable[EventAnnotationRow],
    final_config: Any,
    *,
    chain_succeeded: bool,
) -> tuple[EventAnnotationRow, ...]:
    """用最终配置刷新标注行；普通事件明确不适用威胁判定，未知/失败显式标记。"""
    rows: list[EventAnnotationRow] = []
    for row in annotations:
        if row.status == "uncertain":
            rows.append(row.model_copy(update={"threat_types": (NOT_GENERATED_LABEL,)}))
            continue
        if row.event_name not in THREAT_EVENT_NAMES:
            rows.append(
                row.model_copy(update={"threat_source_field": "不适用", "threat_types": ("不适用",)})
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
    "event_type_determination",
    "refresh_report_event_annotations",
]
