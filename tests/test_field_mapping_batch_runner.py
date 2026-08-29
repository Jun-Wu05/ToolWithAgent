"""Issue #136：FieldMappingBatchRunner 行为冻结与 Adapter 接缝。"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from types import SimpleNamespace


class _MappingMember:
    """记录字段批次并按逆序返回，验证 Runner 恢复输入顺序。"""

    name = "FieldMappingAgent"

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def arun(self, model_input, *, stream, stream_events):
        """返回 Agno 风格完成事件。"""
        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = tuple(json.loads(match.group(1)))
        self.calls.append(fields)
        rows = [
            {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
            for field in reversed(fields)
        ]
        yield SimpleNamespace(event="RunCompleted", content=rows)


def test_runner接口不接收session且26字段保持两批与输入顺序() -> None:
    """Runner 的小接口隐藏批处理实现，不拥有 Session。"""
    from application.field_mapping_batch import (
        FieldMappingBatchRunner,
        FieldMappingExecutionPolicy,
    )

    assert "session" not in inspect.signature(FieldMappingBatchRunner.run).parameters
    member = _MappingMember()
    runner = FieldMappingBatchRunner(
        SimpleNamespace(members=[member]),
        policy=FieldMappingExecutionPolicy(backfill_max_attempts=0),
        candidate_retriever=lambda fields: "",
    )
    events = []

    async def publish_progress(phase, status, message_code, **details):
        events.append((phase, status, message_code, details))

    fields = [f"field_{index:02d}" for index in range(26)]
    rows = asyncio.run(
        runner.run(
            fields,
            original_log_sample="",
            plan_id="runner-plan",
            step_id="mapping",
            publish_progress=publish_progress,
        )
    )

    assert [len(call) for call in member.calls] == [25, 1]
    assert [row["原始字段名"] for row in rows] == fields
    assert sum(event[2] == "field_candidates_retrieving" for event in events) == 2
    assert sum(event[2] == "field_mapping_batch_completed" for event in events) == 2


def test_adapter只调用一次fake_runner并在成功后提交session() -> None:
    """Adapter 通过真实接缝获得完整行，再负责类型化产物与 Session 提交。"""
    from application.adapters.field_mapping import FieldMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import FieldMappingStep, StepStatus

    class RecordingRunner:
        def __init__(self) -> None:
            self.calls = []

        async def run(self, fields, **kwargs):
            self.calls.append((tuple(fields), kwargs))
            return [
                {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
                for field in fields
            ]

    runner = RecordingRunner()
    session = {"decoded_fields": ["src", "dst"]}
    step = FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields")
    result = asyncio.run(
        FieldMappingAdapter(team=None, batch_runner=runner).execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == ("src", "dst")
    assert "session" not in runner.calls[0][1]
    assert [row["原始字段名"] for row in session["last_mapping_data"]] == ["src", "dst"]


def test_runner失败由adapter映射稳定错误且不提交session() -> None:
    """Runner 失败保留稳定错误码，Adapter 不留下部分业务状态。"""
    from application.adapters.field_mapping import FieldMappingAdapter
    from application.execution import ExecutionContext
    from application.field_mapping_batch import FieldMappingBatchError
    from application.session_projection import build_session_facts
    from contracts.planner_models import FieldMappingStep, StepStatus

    class FailedRunner:
        async def run(self, fields, **kwargs):
            raise FieldMappingBatchError(1, "field_mapping_timeout", "第 1 批字段映射失败")

    session = {"decoded_fields": ["src"]}
    step = FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields")
    result = asyncio.run(
        FieldMappingAdapter(team=None, batch_runner=FailedRunner()).execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.FAILED
    assert result.error_code == "field_mapping_timeout"
    assert "last_mapping_data" not in session
    assert "mapped_sub_rules" not in session
