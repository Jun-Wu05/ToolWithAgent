"""统一 PlanExecutor 的依赖、停止和结果验证测试。"""

import asyncio

from web.plan_executor import ExecutionContext, PlanExecutor
from contracts.planner_models import (
    EnumValuesArtifact,
    PlanDecision,
    StepResult,
    StepStatus,
    ThreatMappingArtifact,
)
from contracts.session_facts import SessionFacts


class RecordingAdapter:
    """记录调用并返回预设结果的测试适配器。"""

    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    async def execute(self, step, context, dependencies):
        """保存类型化入参，证明执行器没有传递任意步骤字典。"""
        self.calls.append((step, dependencies))
        return next(self.results)


def _execute(decision, adapters, facts=None):
    """用独立事件循环运行执行器，避免测试依赖额外 pytest 插件。"""
    return asyncio.run(
        PlanExecutor(adapters).execute(
            decision,
            ExecutionContext(session=object(), session_facts=facts or SessionFacts()),
        )
    )


def test步骤失败后立即停止且不调用后续适配器():
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-stop",
            "steps": [
                {"step_id": "extract", "type": "enum_extract", "target_field": "event_type3"},
                {
                    "step_id": "threat",
                    "type": "threat_mapping",
                    "source_ref": "step:extract",
                    "depends_on": ["extract"],
                },
            ],
        }
    )
    extract_adapter = RecordingAdapter(
        [
            StepResult(
                step_id="extract",
                operation_type="enum_extract",
                status=StepStatus.FAILED,
                error_code="enum_extract_failed",
            )
        ]
    )
    threat_adapter = RecordingAdapter([])

    report = _execute(
        decision,
        {"enum_extract": extract_adapter, "threat_mapping": threat_adapter},
        SessionFacts(has_logs=True, available_fields=("event_type3",)),
    )

    assert report.status == StepStatus.FAILED
    assert len(report.results) == 1
    assert threat_adapter.calls == []


def test三步计划只消费本次显式依赖的产物():
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-three",
            "steps": [
                {"step_id": "extract", "type": "enum_extract", "target_field": "event_type3"},
                {
                    "step_id": "threat",
                    "type": "threat_mapping",
                    "source_ref": "step:extract",
                    "depends_on": ["extract"],
                },
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "threat",
                    "target_fields": ["event_type3"],
                    "source_ref": "step:threat",
                    "config_ref": "session.mapped_sub_rules",
                    "depends_on": ["threat"],
                },
            ],
        }
    )
    enum_artifact = EnumValuesArtifact(values=("a", "b"), item_count=2)
    threat_artifact = ThreatMappingArtifact(
        mappings=(
            {
                "mappingType": "EQUAL",
                "orgValue": "a",
                "mappingValue": "x",
            },
        ),
        item_count=1,
    )
    extract_adapter = RecordingAdapter(
        [StepResult(step_id="extract", operation_type="enum_extract", status="success", artifact=enum_artifact)]
    )
    threat_adapter = RecordingAdapter(
        [StepResult(step_id="threat", operation_type="threat_mapping", status="success", artifact=threat_artifact)]
    )
    fill_adapter = RecordingAdapter(
        [StepResult(step_id="fill", operation_type="fill", status="success", changed_count=1)]
    )

    report = _execute(
        decision,
        {"enum_extract": extract_adapter, "threat_mapping": threat_adapter, "fill": fill_adapter},
        SessionFacts(
            has_logs=True,
            has_decoded_config=True,
            has_mapped_sub_rules=True,
            available_config_refs=("session.mapped_sub_rules",),
            available_fields=("event_type3",),
        ),
    )

    assert report.status == StepStatus.SUCCESS
    assert threat_adapter.calls[0][1] == {"extract": report.results[0]}
    assert fill_adapter.calls[0][1] == {"threat": report.results[1]}


def test枚举提取目标字段未出现在字段映射列表时仍进入适配器():
    """枚举提取消费原始日志，不应复用字段映射的 available_fields 门槛。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-field",
            "steps": [{"step_id": "extract", "type": "enum_extract", "target_field": "missing"}],
        }
    )
    adapter = RecordingAdapter(
        [
            StepResult(
                step_id="extract",
                operation_type="enum_extract",
                status=StepStatus.SUCCESS,
                artifact=EnumValuesArtifact(item_count=1, values=("value",)),
            )
        ]
    )

    report = _execute(
        decision,
        {"enum_extract": adapter},
        SessionFacts(has_logs=True, available_fields=("event_type3",)),
    )

    assert report.results[0].status == StepStatus.SUCCESS
    assert report.results[0].artifact.values == ("value",)
    assert len(adapter.calls) == 1


def test字段映射无可用字段时在适配器前拦截():
    """无可用字段时以 fields_required 拦截，适配器不被调用（回归 #40）。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-field-mapping",
            "steps": [{"step_id": "mapping", "type": "field_mapping", "source_ref": "session.fields"}],
        }
    )
    adapter = RecordingAdapter([])

    report = _execute(
        decision,
        {"field_mapping": adapter},
        SessionFacts(available_fields=()),
    )

    assert report.results[0].status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "fields_required"
    assert adapter.calls == []


def test枚举填充目标字段不在映射表时在适配器前拦截():
    """目标字段不在枚举映射表时以 mapping_target_unavailable 拦截（回归 #36）。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-enum-fill",
            "steps": [
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "enum",
                    "target_fields": ["missing"],
                    "source_ref": "session.enum_mapping_table",
                    "config_ref": "session.mapped_sub_rules",
                }
            ],
        }
    )
    adapter = RecordingAdapter([])

    report = _execute(
        decision,
        {"fill": adapter},
        SessionFacts(
            has_mapped_sub_rules=True,
            available_config_refs=("session.mapped_sub_rules",),
            enum_mapping_target_fields=("event_type3",),
        ),
    )

    assert report.results[0].status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "mapping_target_unavailable"
    assert adapter.calls == []


def test填充声称成功但零变更时判定失败():
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-no-change",
            "steps": [
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "enum",
                    "target_fields": ["event_type3"],
                    "source_ref": "session.enum_mapping_table",
                    "config_ref": "session.mapped_sub_rules",
                }
            ],
        }
    )
    adapter = RecordingAdapter(
        [StepResult(step_id="fill", operation_type="fill", status="success", changed_count=0)]
    )

    report = _execute(
        decision,
        {"fill": adapter},
        SessionFacts(
            has_decoded_config=True,
            has_mapped_sub_rules=True,
            available_config_refs=("session.mapped_sub_rules",),
            enum_mapping_target_fields=("event_type3",),
        ),
    )

    assert report.results[0].status == StepStatus.FAILED
    assert report.results[0].error_code == "no_effect"
