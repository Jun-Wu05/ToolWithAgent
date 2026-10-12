"""字段映射目标一对一冲突的确定性裁决。"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agent.shared.mapping_utils import iter_normalize_entries


logger = logging.getLogger("execution_adapters")

CandidateTable = dict[str, list[tuple[str, float, str, str]]]
"""结构化候选表：原始字段名 → [(系统属性名称, 相似度, 字段英文名, by_stripped变体)]（#180）。"""

CandidateRetriever = Callable[[list[str]], CandidateTable]


@dataclass(frozen=True)
class FieldMappingConflictDetail:
    """一组标准字段占用冲突的裁决明细。"""

    standard_field: str
    winner: str
    losers: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class FieldMappingConflictOutcome:
    """裁决后的映射行与全部冲突明细。"""

    rows: tuple[dict[str, Any], ...]
    details: tuple[FieldMappingConflictDetail, ...]


def _is_successful_mapping(row: Mapping[str, Any]) -> bool:
    status = str(row.get("匹配状态") or "").strip()
    standard = str(row.get("系统属性名称") or "").strip()
    return "匹配成功" in status and bool(standard) and standard != "未匹配"


def _collect_existing_assignments(decoded_data: Any) -> dict[str, tuple[str, ...]]:
    """收集上传配置中应由 #163 原样保留的非空 field 占用。"""
    assignments: dict[str, list[str]] = defaultdict(list)
    for _path, _position, _owner, entry in iter_normalize_entries(decoded_data):
        original = str(entry.get("index") or "").strip()
        standard = str(entry.get("field") or "").strip()
        if original and standard and original not in assignments[standard]:
            assignments[standard].append(original)
    return {standard: tuple(originals) for standard, originals in assignments.items()}


def _table_to_scores(table: CandidateTable) -> dict[str, dict[str, float]]:
    """把结构化候选表折叠为 original → standard → 最高相似度。"""
    scores: dict[str, dict[str, float]] = {}
    for original, rows in table.items():
        best: dict[str, float] = {}
        for standard, score, _english, _variant in rows:
            best[standard] = max(score, best.get(standard, float("-inf")))
        if best:
            scores[original] = best
    return scores


def _choose_new_winner(
    members: list[tuple[int, str]],
    standard_field: str,
    candidate_scores: Mapping[str, Mapping[str, float]],
    *,
    retrieval_available: bool,
) -> tuple[int, str]:
    """按精确命中、目标相似度、原行序依次选出保留行。"""
    if not retrieval_available:
        return members[0][0], "候选检索不可用，按原行序"

    evidence = [
        (index, original, candidate_scores.get(original, {}).get(standard_field))
        for index, original in members
    ]
    exact = [item for item in evidence if item[2] is not None and item[2] >= 0.999]
    if len(exact) == 1:
        return exact[0][0], "精确命中（1.00）"
    if len(exact) > 1:
        return min(exact, key=lambda item: item[0])[0], "原行序优先"

    scored = [item for item in evidence if item[2] is not None]
    if scored:
        best_score = max(float(item[2]) for item in scored)
        best = [item for item in scored if float(item[2]) == best_score]
        if len(best) == 1:
            return best[0][0], f"候选相似度 {best_score:.2f}"
    return members[0][0], "原行序优先"


def resolve_field_mapping_conflicts(
    mapping_rows: list[dict[str, Any]],
    *,
    decoded_data: Any = None,
    candidate_retriever: CandidateRetriever | None = None,
) -> FieldMappingConflictOutcome:
    """保证不同原始字段不会在本次映射后占用同一标准字段。"""
    rows = copy.deepcopy(mapping_rows)
    existing = _collect_existing_assignments(decoded_data)
    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for index, row in enumerate(rows):
        if not _is_successful_mapping(row):
            continue
        original = str(row.get("原始字段名") or "").strip()
        standard = str(row.get("系统属性名称") or "").strip()
        if original:
            grouped[standard].append((index, original))

    conflict_groups: list[tuple[str, list[tuple[int, str]]]] = []
    for standard, members in grouped.items():
        originals = {*existing.get(standard, ()), *(original for _, original in members)}
        if len(originals) > 1:
            conflict_groups.append((standard, members))
    if not conflict_groups:
        return FieldMappingConflictOutcome(rows=tuple(rows), details=())

    rankable_fields: list[str] = []
    for standard, members in conflict_groups:
        if existing.get(standard):
            continue
        for _, original in members:
            if original not in rankable_fields:
                rankable_fields.append(original)

    retrieval_available = True
    candidate_scores: dict[str, dict[str, float]] = {}
    if rankable_fields:
        retriever = candidate_retriever
        if retriever is None:
            from agent.core.field_retriever import batch_retrieve_candidates_table

            retriever = batch_retrieve_candidates_table
        try:
            candidate_table = retriever(rankable_fields)
            retrieval_available = bool(candidate_table)
            if retrieval_available:
                candidate_scores = _table_to_scores(candidate_table)
        except Exception as error:  # noqa: BLE001 - 可用性优先，稳定降级到行序
            retrieval_available = False
            logger.warning(
                "[FIELD_MAPPING_CONFLICT] 候选检索不可用，降级为原行序: %s",
                type(error).__name__,
            )

    details: list[FieldMappingConflictDetail] = []
    for standard, members in conflict_groups:
        occupied = existing.get(standard, ())
        if occupied:
            occupied_set = set(occupied)
            loser_members = [member for member in members if member[1] not in occupied_set]
            if not loser_members:
                continue
            winner = "、".join(occupied)
            winner_index = None
            reason = "既有上传映射占用"
        else:
            winner_index, reason = _choose_new_winner(
                members,
                standard,
                candidate_scores,
                retrieval_available=retrieval_available,
            )
            winner = next(original for index, original in members if index == winner_index)
            loser_members = [member for member in members if member[0] != winner_index]

        for loser_index, _ in loser_members:
            rows[loser_index]["系统属性名称"] = "未匹配"
            rows[loser_index]["匹配状态"] = "未匹配"
        details.append(
            FieldMappingConflictDetail(
                standard_field=standard,
                winner=winner,
                losers=tuple(original for _, original in loser_members),
                reason=reason,
            )
        )

    return FieldMappingConflictOutcome(rows=tuple(rows), details=tuple(details))


def format_field_mapping_conflicts(
    details: tuple[FieldMappingConflictDetail, ...],
) -> str:
    """构造用户可见的冲突汇总计数；逐组裁决依据见 log_field_mapping_conflicts（#219）。"""
    if not details:
        return ""
    loser_count = sum(len(detail.losers) for detail in details)
    return (
        f"检测到 {len(details)} 组占用冲突，保留 {len(details)} 个、"
        f"{loser_count} 个置未匹配"
    )


def log_field_mapping_conflicts(
    details: tuple[FieldMappingConflictDetail, ...],
    *,
    plan_id: str,
    step_id: str,
) -> None:
    """逐组把裁决明细落后端日志，风格与 [FIELD_MAPPING_WRITEBACK] 一致（#219）。"""
    for index, detail in enumerate(details, 1):
        logger.info(
            "[FIELD_MAPPING_CONFLICTS] plan_id=%s step_id=%s group=%s/%s "
            "standard_field=%s winner=%s losers=%s reason=%s",
            plan_id, step_id, index, len(details),
            detail.standard_field, detail.winner, "、".join(detail.losers), detail.reason,
        )


__all__ = [
    "FieldMappingConflictDetail",
    "FieldMappingConflictOutcome",
    "format_field_mapping_conflicts",
    "log_field_mapping_conflicts",
    "resolve_field_mapping_conflicts",
]
