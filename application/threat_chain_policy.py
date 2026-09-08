"""威胁类型链路纯策略（#173）：触发判定、来源字段 X 判定、链路构造与值全覆盖校验。

全部为纯函数（不 IO、不 LLM、不读 session），风险集中点先做先测；
编排（执行后续跑、六阶段日志）在 application/threat_chain.py。
领域决策见 issue #173 定稿：双入口触发、X=相似度最高且覆盖全部威胁子规则、
降级固定值「其他」、存量条目跳过加字段、威胁映射产物填充目标固定为威胁类型。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from contracts.planner_models import (
    AddFieldsStep,
    DeleteFieldsStep,
    EnumExtractStep,
    FieldMappingArtifact,
    FillStep,
    StepResult,
    StepSpec,
    StepStatus,
    ThreatMappingStep,
)
from agent.shared.event_classify import (
    THREAT_EVENT_NAMES,
    THREAT_TYPE_FIELD,
    read_entity_event_name,
)
from agent.tools.rule_generator.field_mapping import EXCLUDED_FIELD_INDICES

THREAT_SOURCE_MIN_SCORE = 0.5
"""X 判定的「接近」门槛：候选表中威胁类型行的相似度下限，低于此判不出走降级。"""

DEGRADED_THREAT_VALUE = "其他"
"""降级链路的威胁类型固定值（threat_type.md「最后手段」语义的正式化）。"""

# 链路四步的固定 step_id（报告可读 + 依赖声明）
ENUM_STEP_ID = "threat-chain-enum"
MAPPING_STEP_ID = "threat-chain-map"
REPLACE_STEP_ID = "threat-chain-replace"
ADD_STEP_ID = "threat-chain-add"
FILL_STEP_ID = "threat-chain-fill"


# S0 触发判定


@dataclass(frozen=True)
class ChainTrigger:
    """字段映射成功后的链路触发判定结果。

    宁缺勿错：待人工确认（uncertain）的子规则不参与链路；全部候选待确认时
    链路不触发，但应向用户提示一句避免困惑（hint_only）。
    """

    threat_rule_names: tuple[str, ...]
    uncertain_rule_names: tuple[str, ...]

    @property
    def should_run(self) -> bool:
        """是否存在已判定的威胁子规则（链路是否应执行）。"""
        return bool(self.threat_rule_names)

    @property
    def hint_only(self) -> bool:
        """无已判定威胁但存在待确认规则：不跑链路，只提示。"""
        return not self.threat_rule_names and bool(self.uncertain_rule_names)


def evaluate_chain_trigger(results: Iterable[StepResult]) -> ChainTrigger | None:
    """从执行报告的结果行里找成功的字段映射产物并判定威胁子规则。

    Returns:
        无成功字段映射步骤时返回 None（链路完全不适用）；
        有则返回触发判定（should_run / hint_only 语义见 ChainTrigger）。
    """
    for result in results:
        if result.status != StepStatus.SUCCESS or result.artifact is None:
            continue
        if not isinstance(result.artifact, FieldMappingArtifact):
            continue
        threat_rules: list[str] = []
        uncertain_rules: list[str] = []
        for row in result.artifact.event_annotations:
            if row.status == "judged" and row.event_name in THREAT_EVENT_NAMES:
                if row.rule_name:
                    threat_rules.append(row.rule_name)
            elif row.status == "uncertain" and row.rule_name:
                uncertain_rules.append(row.rule_name)
        return ChainTrigger(
            threat_rule_names=tuple(dict.fromkeys(threat_rules)),
            uncertain_rule_names=tuple(dict.fromkeys(uncertain_rules)),
        )
    return None


def collect_threat_field_pools(
    mapped_sub_rules: Any, threat_rule_names: tuple[str, ...]
) -> dict[str, tuple[str, ...]]:
    """收集每条威胁子规则的可判定字段池（normalize index，剔除元字段）。

    Returns:
        {rule_name: (index, ...)}；找不到的规则名不出现在结果里。
    """
    pools: dict[str, tuple[str, ...]] = {}
    if not isinstance(mapped_sub_rules, list):
        return pools
    wanted = set(threat_rule_names)
    for rule in mapped_sub_rules:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "")
        if name not in wanted:
            continue
        indexes = tuple(
            str(entry.get("index") or "")
            for entry in rule.get("normalize", [])
            if isinstance(entry, dict)
            and str(entry.get("index") or "")
            and str(entry.get("index")) not in EXCLUDED_FIELD_INDICES
        )
        pools[name] = indexes
    return pools


# S1 来源字段 X 判定


@dataclass(frozen=True)
class SourceFieldDecision:
    """X 判定结论：选中字段（或 None 表示降级）+ 可解释依据。"""

    source_field: str | None
    score: float
    covered_rules: int
    reason: str


def _covering_fields(field_pools: Mapping[str, tuple[str, ...]]) -> set[str]:
    """求出现在全部威胁子规则字段池中的字段（覆盖约束的候选集）。"""
    covering: set[str] | None = None
    for indexes in field_pools.values():
        current = set(indexes)
        covering = current if covering is None else covering & current
    return covering or set()


def determine_source_field(
    field_pools: Mapping[str, tuple[str, ...]],
    candidate_table: Mapping[str, list[tuple[str, float, str, str]]],
    *,
    override: str | None = None,
    min_score: float = THREAT_SOURCE_MIN_SCORE,
) -> SourceFieldDecision:
    """判定威胁来源字段 X：会话覆盖优先，其次相似度最高且覆盖全部威胁子规则。

    Args:
        field_pools: collect_threat_field_pools 的输出。
        candidate_table: batch_retrieve_candidates_table(include_mapping_excluded=True)
            对字段池全量字段的结构化候选表。
        override: 会话级来源覆盖值（用户显式纠正过 X）。
        min_score: 「接近」门槛。

    Returns:
        SourceFieldDecision；source_field 为 None 时走降级链路（reason 说明原因）。
    """
    total_rules = len(field_pools)
    covering = _covering_fields(field_pools)

    if override is not None:
        if override in covering:
            return SourceFieldDecision(override, 1.0, total_rules, "session_override")
        return SourceFieldDecision(None, 0.0, 0, "override_not_covering")

    if not covering:
        return SourceFieldDecision(None, 0.0, 0, "degrade_no_coverage")

    scored: list[tuple[float, str]] = []
    for candidate_field in covering:
        best = 0.0
        for row in candidate_table.get(candidate_field, ()):
            if row[0] == THREAT_TYPE_FIELD and row[1] > best:
                best = row[1]
        scored.append((best, candidate_field))
    scored.sort(key=lambda item: (-item[0], item[1]))

    if not scored or scored[0][0] < min_score:
        return SourceFieldDecision(None, 0.0, 0, "degrade_below_threshold")

    best_score, best_field = scored[0]
    return SourceFieldDecision(best_field, best_score, total_rules, "similarity")


# 威胁类型字段现状探测（构造分支依据）

THREAT_FIELD_ABSENT = "absent"
"""目标配置中无威胁类型条目：正常 add + fill。"""
THREAT_FIELD_CHAIN = "chain"
"""威胁类型条目带 %{引用} 绑定（本链路先前产物）：先删后加整体替换。"""
THREAT_FIELD_EXISTING = "existing"
"""威胁类型为存量条目（上传配置历史/他方写入）：跳过加字段，直接填充。"""


def inspect_threat_field_state(
    config: Any, threat_rule_names: tuple[str, ...]
) -> str:
    """探测威胁组子规则中威胁类型字段的现状，决定链路的加字段分支。

    判定规则（确定性）：
    - addFields 绑定过滤器含 ``威胁类型: %{...}`` 引用值 → chain（链路自产）
    - normalize 条目 index 或 field 命中威胁类型 → existing（存量）
    - 都没有 → absent
    """
    if not isinstance(config, list):
        return THREAT_FIELD_ABSENT
    wanted = set(threat_rule_names)
    has_entry = False
    for rule in config:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "")
        if name not in wanted:
            continue
        for entry in rule.get("normalize", []):
            if not isinstance(entry, dict):
                continue
            if (
                entry.get("index") == THREAT_TYPE_FIELD
                or entry.get("field") == THREAT_TYPE_FIELD
            ):
                has_entry = True
        parser = rule.get("parser")
        if isinstance(parser, dict):
            for filter_item in parser.get("filter", []):
                if not isinstance(filter_item, dict):
                    continue
                if filter_item.get("name") != "addFields" or filter_item.get("id") != "":
                    continue
                fields = filter_item.get("fields")
                if isinstance(fields, dict):
                    if THREAT_TYPE_FIELD in fields:
                        return THREAT_FIELD_CHAIN
    return THREAT_FIELD_EXISTING if has_entry else THREAT_FIELD_ABSENT


# 链路构造器


@dataclass(frozen=True)
class ThreatChainPlan:
    """构造出的链路计划：类型化步骤 + 摘要要素。"""

    steps: tuple[StepSpec, ...]
    degraded: bool
    skipped_add_reason: str = ""
    summary_parts: tuple[str, ...] = field(default=())


def build_threat_chain_steps(
    source_decision: SourceFieldDecision,
    *,
    config_ref: str,
    threat_field_state: str = THREAT_FIELD_ABSENT,
) -> ThreatChainPlan:
    """把 X 判定结论构造成类型化步骤序列（降级单步或四步全链）。

    Args:
        source_decision: determine_source_field 的输出。
        config_ref: 链路目标配置（自动入口固定 session.mapped_sub_rules）。
        threat_field_state: inspect_threat_field_state 的输出，决定加字段分支。
    """
    if source_decision.source_field is None:
        degraded_steps: list[StepSpec] = []
        if threat_field_state == THREAT_FIELD_CHAIN:
            degraded_steps.append(
                DeleteFieldsStep(
                    step_id=REPLACE_STEP_ID,
                    type="delete_fields",
                    fields=(THREAT_TYPE_FIELD,),
                    rule_group="threat",
                    config_ref=config_ref,
                )
            )
        add_dependencies = (
            (REPLACE_STEP_ID,) if threat_field_state == THREAT_FIELD_CHAIN else ()
        )
        degraded_steps.append(
            AddFieldsStep(
                step_id=ADD_STEP_ID,
                type="add_fields",
                field_name=THREAT_TYPE_FIELD,
                field_value=DEGRADED_THREAT_VALUE,
                value_type="fixed",
                rule_group="threat",
                config_ref=config_ref,
                depends_on=add_dependencies,
            )
        )
        return ThreatChainPlan(
            steps=tuple(degraded_steps),
            degraded=True,
            summary_parts=(
                f"来源字段判不出（{source_decision.reason}），已降级固定值"
                f"「{DEGRADED_THREAT_VALUE}」；可用显式指令指定来源字段重跑",
            ),
        )

    source_field = source_decision.source_field
    steps: list[StepSpec] = [
        EnumExtractStep(
            step_id=ENUM_STEP_ID,
            type="enum_extract",
            target_field=source_field,
        ),
        ThreatMappingStep(
            step_id=MAPPING_STEP_ID,
            type="threat_mapping",
            source_ref=f"step:{ENUM_STEP_ID}",
            depends_on=(ENUM_STEP_ID,),
        ),
    ]
    if threat_field_state == THREAT_FIELD_CHAIN:
        steps.append(
            DeleteFieldsStep(
                step_id=REPLACE_STEP_ID,
                type="delete_fields",
                fields=(THREAT_TYPE_FIELD,),
                rule_group="threat",
                config_ref=config_ref,
                depends_on=(MAPPING_STEP_ID,),
            )
        )
    if threat_field_state != THREAT_FIELD_EXISTING:
        steps.append(
            AddFieldsStep(
                step_id=ADD_STEP_ID,
                type="add_fields",
                field_name=THREAT_TYPE_FIELD,
                field_value=f"%{{{source_field}}}",
                value_type="reference",
                rule_group="threat",
                config_ref=config_ref,
                depends_on=(MAPPING_STEP_ID,),
            )
        )
    steps.append(
        FillStep(
            step_id=FILL_STEP_ID,
            type="fill",
            fill_kind="threat",
            target_fields=(THREAT_TYPE_FIELD,),
            source_ref=f"step:{MAPPING_STEP_ID}",
            config_ref=config_ref,
            depends_on=(MAPPING_STEP_ID,),
        )
    )
    skipped_reason = (
        "配置已含威胁类型存量条目，跳过加字段直接填充"
        if threat_field_state == THREAT_FIELD_EXISTING
        else ""
    )
    return ThreatChainPlan(
        steps=tuple(steps),
        degraded=False,
        skipped_add_reason=skipped_reason,
        summary_parts=(
            f"来源字段={source_field}（得分 {source_decision.score:.2f}，"
            f"覆盖 {source_decision.covered_rules} 条威胁子规则）",
        ),
    )


# 值全覆盖校验（S3 后、S5 前的确定性兜底）


def _row_covers_value(row: Mapping[str, Any], value: str) -> bool:
    """判断映射行的 orgValue 是否覆盖该提取值（REGULAR 正则或 EQUAL 字面）。"""
    org_value = str(row.get("orgValue") or "")
    if not org_value:
        return False
    mapping_type = str(row.get("mappingType") or "EQUAL")
    if mapping_type == "REGULAR":
        try:
            return re.fullmatch(org_value, value) is not None
        except re.error:
            return False
    return org_value == value


def ensure_threat_mapping_coverage(
    values: Iterable[str], rows: list[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """确定性全覆盖校验：未被任何映射行覆盖的提取值补「其他」兜底行。

    不依赖提示词自觉（issue #173 领域决策 5）；原地追加到 rows 副本并返回。
    """
    covered_rows = list(rows)
    for value in values:
        value = str(value)
        if any(_row_covers_value(row, value) for row in covered_rows):
            continue
        covered_rows.append(
            {
                "mappingType": "REGULAR",
                "orgValue": f"(?i).*{re.escape(value)}.*",
                "mappingValue": DEGRADED_THREAT_VALUE,
            }
        )
    return covered_rows


__all__ = [
    "ADD_STEP_ID",
    "ChainTrigger",
    "DEGRADED_THREAT_VALUE",
    "ENUM_STEP_ID",
    "FILL_STEP_ID",
    "MAPPING_STEP_ID",
    "REPLACE_STEP_ID",
    "THREAT_FIELD_ABSENT",
    "THREAT_FIELD_CHAIN",
    "THREAT_FIELD_EXISTING",
    "THREAT_SOURCE_MIN_SCORE",
    "ThreatChainPlan",
    "build_threat_chain_steps",
    "collect_threat_field_pools",
    "determine_source_field",
    "ensure_threat_mapping_coverage",
    "evaluate_chain_trigger",
    "inspect_threat_field_state",
    "read_entity_event_name",
]
