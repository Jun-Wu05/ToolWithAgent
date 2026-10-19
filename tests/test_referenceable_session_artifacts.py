"""Issue #80：可引用会话产物的契约、生命周期与跨轮执行回归。"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from agent.core.planner import build_planner_input
from contracts.planner_models import (
    EnumValuesArtifact,
    FillStep,
    PlanDecision,
    StepResult,
    StepStatus,
    ThreatMappingArtifact,
    ThreatMappingRow,
    ThreatMappingStep,
)
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
from application.session_projection import build_session_facts
from application.adapters import create_default_adapters
from application.enum_mapping_attachments import commit_enum_mapping_attachment
from application.execution import ExecutionContext, PlanExecutor
from factories import make_session_state


def _threat_artifact(source_field: str | None = "alarm_name") -> ThreatMappingArtifact:
    """构造单行威胁映射，供跨轮测试复用。"""
    row = ThreatMappingRow.model_validate(
        {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "恶意活动"}
    )
    return ThreatMappingArtifact(
        mappings=(row,),
        item_count=1,
        source_field=source_field,
    )


def _enum_slot(field: str = "alarm_name", value: str = "attack") -> EnumArtifactSlot:
    """构造带字段血缘的最近枚举产物。"""
    artifact = EnumValuesArtifact(
        values=(value,),
        item_count=1,
        field=field,
    )
    return EnumArtifactSlot(artifact=artifact, source_field=field)


def _threat_slot(source_field: str | None = "alarm_name") -> ThreatArtifactSlot:
    """构造最近威胁产物槽。"""
    artifact = _threat_artifact(source_field)
    return ThreatArtifactSlot(artifact=artifact, source_field=source_field)


class _ThreatMember:
    """返回固定威胁映射内容的同步专业 Agent 替身。"""

    name = "ThreatAgent"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def run(self, model_input: str) -> str:
        self.calls.append(model_input)
        return self.response


class _Team:
    """提供单个测试成员的 Team 替身。"""

    def __init__(self, member: _ThreatMember) -> None:
        self.members = [member]


def test新source_ref强制与直接值和步骤依赖互斥():
    """白名单 session 来源不得混入 values 或本轮依赖。"""
    step = ThreatMappingStep(
        step_id="threat",
        type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )
    assert step.depends_on == ()

    with pytest.raises(ValidationError):
        ThreatMappingStep(
            step_id="threat",
            type="threat_mapping",
            source_ref="session.artifacts.enum_values",
            values=("attack",),
        )
    with pytest.raises(ValidationError):
        FillStep(
            step_id="fill",
            type="fill",
            fill_kind="threat",
            target_fields=("event_name",),
            source_ref="session.artifacts.threat_mapping",
            config_ref="session.decoded_config",
            depends_on=("threat",),
        )
    with pytest.raises(ValidationError):
        FillStep(
            step_id="fill",
            type="fill",
            fill_kind="threat",
            target_fields=(),
            source_ref="session.artifacts.threat_mapping",
            config_ref="session.decoded_config",
        )
    with pytest.raises(ValidationError):
        ThreatMappingStep(
            step_id="threat",
            type="threat_mapping",
            source_ref="session.last_enum_extract_result",
        )


def testSessionFacts只暴露安全产物目录和固定威胁绑定():
    """Planner 输入包含字段血缘但不得包含真实枚举值或威胁映射行。"""
    session = make_session_state(
        decoded_data={
            "normalize": [
                {"index": "alarm_name", "field": "event_name", "mappings": []}
            ]
        },
        latest_enum_artifact=_enum_slot(value="敏感枚举值"),
        latest_threat_artifact=ThreatArtifactSlot(
            artifact=ThreatMappingArtifact(
                mappings=(
                    ThreatMappingRow.model_validate(
                        {
                            "mappingType": "EQUAL",
                            "orgValue": "敏感原值",
                            "mappingValue": "敏感映射值",
                        }
                    ),
                ),
                item_count=1,
                source_field="alarm_name",
            ),
            source_field="alarm_name",
        ),
    )

    facts = build_session_facts(session)
    assert [item.source_ref for item in facts.referenceable_artifacts] == [
        "session.artifacts.enum_values",
        "session.artifacts.threat_mapping",
    ]
    enum_fact, threat_fact = facts.referenceable_artifacts
    # 枚举产物仍按 source_field 血缘解析绑定（多目标合法）
    assert enum_fact.target_bindings[0].target_field == "event_name"
    # 威胁产物填充目标固定为「威胁类型」（#173 修复 1）；配置无该条目时不发布绑定
    assert threat_fact.target_bindings == ()

    session.decoded_data["normalize"].append({"index": "威胁类型", "mappings": []})
    facts_with_entry = build_session_facts(session)
    threat_bindings = facts_with_entry.referenceable_artifacts[1].target_bindings
    assert [(b.config_ref, b.target_field) for b in threat_bindings] == [
        ("session.decoded_config", "威胁类型")
    ]
    planner_input = build_planner_input("填充回去", [], facts)
    assert "敏感枚举值" not in planner_input
    assert "敏感原值" not in planner_input
    assert "敏感映射值" not in planner_input


def test旧last结果不会自动升级为可引用产物():
    """展示兼容键仍可计数，但不能进入 Planner 可执行目录。"""
    facts = build_session_facts(
        make_session_state(
            last_enum_extract_result={"value": ["old"]},
            last_threat_data=[{"orgValue": "old"}],
        )
    )
    assert facts.existing_enum_value_count == 1
    assert facts.existing_threat_mapping_count == 1
    assert facts.referenceable_artifacts == ()


def test主数据清空同时清除两个可引用产物():
    """可引用会话产物与当前主数据共享生命周期。"""
    session = make_session_state(
        decoded_data={"normalize": []},
        latest_enum_artifact=_enum_slot(),
        latest_threat_artifact=_threat_slot(),
    )
    session.clear_decoded_data()
    assert session.latest_enum_artifact is None
    assert session.latest_threat_artifact is None


def test枚举映射附件上传不清除可引用产物():
    """附件只更新映射表集合，不改变两类成功产物的生命周期。"""
    enum_slot = _enum_slot()
    threat_slot = _threat_slot()
    session = make_session_state(
        latest_enum_artifact=enum_slot,
        latest_threat_artifact=threat_slot,
    )

    commit_enum_mapping_attachment(
        session,
        "enum.xlsx",
        {
            "event_name": [
                {
                    "mappingType": "EQUAL",
                    "orgValue": "attack",
                    "mappingValue": "攻击",
                }
            ]
        },
    )

    assert session.latest_enum_artifact == enum_slot
    assert session.latest_threat_artifact == threat_slot


def test上轮枚举产物可直接用于本轮威胁映射():
    """ThreatAgent 消费类型化枚举槽，不重新执行枚举提取。"""
    member = _ThreatMember(
        json.dumps(
            [{"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "恶意程序"}],
            ensure_ascii=False,
        )
    )
    adapter = create_default_adapters(_Team(member))["threat_mapping"]
    session = make_session_state(latest_enum_artifact=_enum_slot())
    step = ThreatMappingStep(
        step_id="threat",
        type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert json.loads(member.calls[0]) == {"values": ["attack"]}
    assert session.latest_threat_artifact.source_field == "alarm_name"


def test威胁映射失败保留上次成功产物():
    """失败步骤没有新产物，不得覆盖可继续使用的成功结果。"""
    previous = _threat_slot("old_field")
    session = make_session_state(
        latest_enum_artifact=_enum_slot(),
        latest_threat_artifact=previous,
    )
    adapter = create_default_adapters(_Team(_ThreatMember("[]")))["threat_mapping"]
    step = ThreatMappingStep(
        step_id="threat",
        type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.FAILED
    assert session.latest_threat_artifact == previous


def test威胁映射覆盖校验失败保留上次成功产物():
    """结构合法但来源外的映射结果必须拒绝，旧成功产物继续可引用（#277）。"""
    previous = _threat_slot("old_field")
    session = make_session_state(
        latest_enum_artifact=_enum_slot(),
        latest_threat_artifact=previous,
    )
    member = _ThreatMember(
        json.dumps(
            [
                {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "暴力破解"},
                {"mappingType": "EQUAL", "orgValue": "out-of-source", "mappingValue": "端口扫描"},
            ],
            ensure_ascii=False,
        )
    )
    adapter = create_default_adapters(_Team(member))["threat_mapping"]
    step = ThreatMappingStep(
        step_id="threat",
        type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.FAILED
    assert result.error_code == "threat_mapping_coverage_rejected"
    assert session.latest_threat_artifact == previous
    assert session.last_threat_data is None


def test全数字枚举产物触发needs_input不覆盖旧产物():
    """无语义数字代码不允许模型猜测：needs_input 且不污染旧成功产物（#277）。"""
    previous = _threat_slot("old_field")
    session = make_session_state(
        latest_enum_artifact=_enum_slot(value="30"),
        latest_threat_artifact=previous,
    )
    member = _ThreatMember("[]")
    adapter = create_default_adapters(_Team(member))["threat_mapping"]
    step = ThreatMappingStep(
        step_id="threat",
        type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.NEEDS_INPUT
    assert result.error_code == "threat_mapping_source_context_required"
    assert member.calls == []
    assert session.latest_threat_artifact == previous


def _execute_cross_turn_fill(session, target_field: str) -> StepResult:
    """通过真实 PlanExecutor 执行单步跨轮威胁填充。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "reuse-threat",
            "steps": [
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "threat",
                    "target_fields": [target_field],
                    "source_ref": "session.artifacts.threat_mapping",
                    "config_ref": "session.decoded_config",
                }
            ],
        }
    )
    report = asyncio.run(
        PlanExecutor(create_default_adapters(team=None)).execute(
            decision,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )
    return report.results[0]


def test上轮威胁产物只能填回固定目标威胁类型():
    """威胁填充目标固定为威胁类型（#173），点名其他字段在执行前拒绝。"""
    session = make_session_state(
        decoded_data={
            "normalize": [
                {"index": "attack_type", "mappings": []},
                {"index": "威胁类型", "mappings": []},
                {"index": "other", "field": "other_standard", "mappings": []},
            ]
        },
        latest_threat_artifact=_threat_slot("attack_type"),
    )
    mismatch = _execute_cross_turn_fill(session, "other_standard")
    assert mismatch.status == StepStatus.NEEDS_INPUT
    assert mismatch.error_code == "threat_fill_target_fixed"
    assert session.decoded_data["normalize"][1]["mappings"] == []

    success = _execute_cross_turn_fill(session, "威胁类型")
    assert success.status == StepStatus.SUCCESS
    assert success.changed_count == 1


def test无来源字段的威胁产物仍只能填威胁类型():
    """无来源字段（user.values）的威胁产物也只能填威胁类型。"""
    session = make_session_state(
        decoded_data={
            "normalize": [
                {"index": "raw_event", "field": "event_name", "mappings": []},
                {"index": "威胁类型", "mappings": []},
            ]
        },
        latest_threat_artifact=_threat_slot(None),
    )
    rejected = _execute_cross_turn_fill(session, "event_name")
    assert rejected.status == StepStatus.NEEDS_INPUT
    assert rejected.error_code == "threat_fill_target_fixed"

    success = _execute_cross_turn_fill(session, "威胁类型")
    assert success.status == StepStatus.SUCCESS


def test产物被清除或执行期类型错配时安全停止():
    """计划不能从缺失或错误类型的 Session 值回退到旧展示结果。"""
    config = {
        "normalize": [{"index": "alarm_name", "field": "event_name", "mappings": []}]
    }
    cleared = _execute_cross_turn_fill(
        make_session_state(decoded_data=config), "event_name"
    )
    assert cleared.status == StepStatus.NEEDS_INPUT
    assert cleared.error_code == "artifact_source_unavailable"

    wrong_type = _execute_cross_turn_fill(
        make_session_state(
            decoded_data=config,
            latest_threat_artifact=_enum_slot(),
            last_threat_data=[
                {"mappingType": "EQUAL", "orgValue": "old", "mappingValue": "旧值"}
            ],
        ),
        "event_name",
    )
    assert wrong_type.status == StepStatus.NEEDS_INPUT
    assert wrong_type.error_code == "artifact_source_unavailable"


def test多字段同轮选择B后血缘仍记录但填充目标固定():
    """即使最近枚举槽为 C，本轮依赖 B 的产物也必须把威胁血缘保存为 B；
    跨轮填充目标固定为威胁类型（#173），血缘只作展示与追溯。"""
    member = _ThreatMember(
        json.dumps(
            [{"mappingType": "EQUAL", "orgValue": "b-value", "mappingValue": "恶意程序"}],
            ensure_ascii=False,
        )
    )
    adapter = create_default_adapters(_Team(member))["threat_mapping"]
    session = make_session_state(latest_enum_artifact=_enum_slot("C", "c-value"))
    b_artifact = EnumValuesArtifact(values=("b-value",), item_count=1, field="B")
    dependency = StepResult(
        step_id="enum-b",
        operation_type="enum_extract",
        status=StepStatus.SUCCESS,
        artifact=b_artifact,
    )
    step = ThreatMappingStep(
        step_id="threat-b",
        type="threat_mapping",
        source_ref="step:enum-b",
        depends_on=("enum-b",),
    )
    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {"enum-b": dependency},
        )
    )
    assert result.status == StepStatus.SUCCESS
    assert session.latest_threat_artifact.source_field == "B"

    session.decoded_data = {
        "normalize": [
            {"index": "B", "field": "standard_b", "mappings": []},
            {"index": "威胁类型", "mappings": []},
        ]
    }
    fill = _execute_cross_turn_fill(session, "威胁类型")
    assert fill.status == StepStatus.SUCCESS
