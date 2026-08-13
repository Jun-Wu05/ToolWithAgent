"""统一 PlanExecutor 的依赖、停止和结果验证测试。"""

import asyncio

from web.plan_executor import ExecutionContext, PlanExecutor
from web.planner_models import (
    EnumValuesArtifact,
    PlanDecision,
    StepResult,
    StepStatus,
    ThreatMappingArtifact,
)
from web.session_facts import SessionFacts


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


def test字段不存在时在调用适配器前拦截():
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-field",
            "steps": [{"step_id": "extract", "type": "enum_extract", "target_field": "missing"}],
        }
    )
    adapter = RecordingAdapter([])

    report = _execute(
        decision,
        {"enum_extract": adapter},
        SessionFacts(has_logs=True, available_fields=("event_type3",)),
    )

    assert report.results[0].status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "target_field_unavailable"
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
