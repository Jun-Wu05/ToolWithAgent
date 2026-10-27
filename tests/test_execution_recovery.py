"""Issue #224：计划执行中的有界瞬时失败恢复。"""

import asyncio
import logging

import pytest

from factories import make_session_state


def test瞬时异常原样重试一次并在报告与审计中标记恢复(caplog) -> None:
    from application.execution import ExecutionContext
    from application.execution_policy import create_plan_executor
    from contracts.planner_models import PlanDecision, StepResult, StepStatus
    from contracts.session_facts import SessionFacts
    from contracts.model_call_diagnostics import bind_recorder, record_call, reset_recorder
    import time
    from datetime import datetime, timezone

    diagnostic_events = []

    class FlakyAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, step, _context, _dependencies):
            self.calls += 1
            for _ in range(2 if self.calls == 2 else 1):
                record_call("test", "model", None, datetime.now(timezone.utc).isoformat(),
                            time.monotonic(), "request", response="response")
            if self.calls == 1:
                raise TimeoutError("temporary provider timeout")
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus.SUCCESS,
                message="日志类型提取完成",
            )

    adapter = FlakyAdapter()
    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-recover-timeout",
            "steps": [{"step_id": "log-1", "type": "log_parse"}],
        }
    )

    token = bind_recorder(diagnostic_events.append)
    try:
        with caplog.at_level(logging.INFO, logger="recovery"):
            report = asyncio.run(
                create_plan_executor({"log_parse": adapter}).execute(
                    plan,
                    ExecutionContext(
                        session=make_session_state(raw_log_lines=["event=login"]),
                        session_facts=SessionFacts(has_logs=True),
                    ),
                )
            )
    finally:
        reset_recorder(token)

    assert report.status == StepStatus.SUCCESS
    assert report.results[0].recovered is True
    assert adapter.calls == 2
    assert [event["attempt"] for event in diagnostic_events] == [1, 2, 2]
    assert all(event["operation"] == "log_parse" for event in diagnostic_events)
    recovery_records = [
        record for record in caplog.records if record.name == "recovery"
    ]
    assert len(recovery_records) == 1
    assert "plan_id=plan-recover-timeout" in recovery_records[0].message
    assert "step_id=log-1" in recovery_records[0].message
    assert "type=retry" in recovery_records[0].message
    assert "error_code=adapter_failed" in recovery_records[0].message
    assert "result=success" in recovery_records[0].message


def test恢复预算为零时保持失败即停且不改变报告序列化() -> None:
    from application.execution import ExecutionContext
    from application.execution_policy import create_plan_executor
    from application.recovery import RecoveryBudget
    from contracts.planner_models import PlanDecision, StepStatus
    from contracts.session_facts import SessionFacts

    class TimeoutAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _step, _context, _dependencies):
            self.calls += 1
            raise TimeoutError("temporary provider timeout")

    adapter = TimeoutAdapter()
    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-recovery-disabled",
            "steps": [{"step_id": "log-1", "type": "log_parse"}],
        }
    )

    report = asyncio.run(
        create_plan_executor({"log_parse": adapter}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(raw_log_lines=["event=login"]),
                session_facts=SessionFacts(has_logs=True),
                recovery_budget=RecoveryBudget(max_per_plan=0),
            ),
        )
    )

    assert report.status == StepStatus.FAILED
    assert adapter.calls == 1
    assert '"recovered"' not in report.model_dump_json()


def test恢复成功的步骤在既有执行报告中标明已自动重试() -> None:
    from contracts.planner_models import ExecutionReport, StepResult, StepStatus
    from web.plan_renderer import build_execution_report_content

    content = build_execution_report_content(
        ExecutionReport(
            plan_id="plan-render-recovery",
            results=(
                StepResult(
                    step_id="enum-1",
                    operation_type="enum_extract",
                    status=StepStatus.SUCCESS,
                    message="枚举提取完成",
                    recovered=True,
                ),
            ),
        )
    )

    assert "枚举提取完成（已自动重试）" in content


def test同一步骤连续两次瞬时失败后停止且不做第三次尝试() -> None:
    from application.execution import ExecutionContext
    from application.execution_policy import create_plan_executor
    from contracts.planner_models import PlanDecision, StepStatus
    from contracts.session_facts import SessionFacts

    class AlwaysTimeoutAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _step, _context, _dependencies):
            self.calls += 1
            raise TimeoutError("temporary provider timeout")

    adapter = AlwaysTimeoutAdapter()
    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-retry-once",
            "steps": [{"step_id": "enum-1", "type": "enum_extract", "target_field": "event"}],
        }
    )

    report = asyncio.run(
        create_plan_executor({"enum_extract": adapter}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(raw_log_lines=["event=login"]),
                session_facts=SessionFacts(
                    has_logs=True,
                    available_fields=("event",),
                ),
            ),
        )
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].recovered is True
    assert adapter.calls == 2


def test计划级预算耗尽后第三个瞬时失败不再重试() -> None:
    from collections import defaultdict

    from application.execution import ExecutionContext
    from application.execution_policy import create_plan_executor
    from contracts.planner_models import PlanDecision, StepResult, StepStatus
    from contracts.session_facts import SessionFacts

    class PerStepFlakyAdapter:
        def __init__(self) -> None:
            self.calls = defaultdict(int)

        async def execute(self, step, _context, _dependencies):
            self.calls[step.step_id] += 1
            if self.calls[step.step_id] == 1:
                raise TimeoutError("temporary provider timeout")
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus.SUCCESS,
            )

    adapter = PerStepFlakyAdapter()
    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-budget-two",
            "steps": [
                {"step_id": "log-1", "type": "log_parse"},
                {"step_id": "log-2", "type": "log_parse"},
                {"step_id": "log-3", "type": "log_parse"},
            ],
        }
    )

    report = asyncio.run(
        create_plan_executor({"log_parse": adapter}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(raw_log_lines=["event=login"]),
                session_facts=SessionFacts(has_logs=True),
            ),
        )
    )

    assert [result.status for result in report.results] == [
        StepStatus.SUCCESS,
        StepStatus.SUCCESS,
        StepStatus.FAILED,
    ]
    assert [result.recovered for result in report.results] == [True, True, False]
    assert dict(adapter.calls) == {"log-1": 2, "log-2": 2, "log-3": 1}


def test模型结构解析失败结果可原样重试后恢复() -> None:
    from application.execution import ExecutionContext
    from application.execution_policy import create_plan_executor
    from contracts.planner_models import PlanDecision, StepResult, StepStatus
    from contracts.session_facts import SessionFacts

    class InvalidThenValidAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, step, _context, _dependencies):
            self.calls += 1
            if self.calls == 1:
                return StepResult(
                    step_id=step.step_id,
                    operation_type=step.type,
                    status=StepStatus.FAILED,
                    error_code="enum_regex_invalid",
                )
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus.SUCCESS,
            )

    adapter = InvalidThenValidAdapter()
    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-recover-invalid-json",
            "steps": [
                {"step_id": "enum-1", "type": "enum_extract", "target_field": "event"}
            ],
        }
    )

    report = asyncio.run(
        create_plan_executor({"enum_extract": adapter}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(raw_log_lines=["event=login"]),
                session_facts=SessionFacts(
                    has_logs=True,
                    available_fields=("event",),
                ),
            ),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert report.results[0].recovered is True
    assert adapter.calls == 2


@pytest.mark.parametrize(
    ("status", "error_code"),
    (
        ("needs_input", "target_field_required"),
        ("failed", "enum_regex_no_match"),
    ),
)
def test待输入与业务失败不触发恢复重试(status, error_code) -> None:
    from application.execution import ExecutionContext
    from application.execution_policy import create_plan_executor
    from contracts.planner_models import PlanDecision, StepResult, StepStatus
    from contracts.session_facts import SessionFacts

    class StableFailureAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, step, _context, _dependencies):
            self.calls += 1
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus(status),
                error_code=error_code,
            )

    adapter = StableFailureAdapter()
    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": f"plan-no-recovery-{status}",
            "steps": [
                {"step_id": "enum-1", "type": "enum_extract", "target_field": "event"}
            ],
        }
    )

    report = asyncio.run(
        create_plan_executor({"enum_extract": adapter}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(raw_log_lines=["event=login"]),
                session_facts=SessionFacts(
                    has_logs=True,
                    available_fields=("event",),
                ),
            ),
        )
    )

    assert report.results[0].status == StepStatus(status)
    assert report.results[0].recovered is False
    assert adapter.calls == 1


def test灰度白名单外的写步骤即使超时也不自动重试() -> None:
    from application.execution import ExecutionContext
    from application.execution_policy import create_plan_executor
    from contracts.planner_models import PlanDecision, StepStatus
    from contracts.session_facts import SessionFacts

    class TimeoutAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, _step, _context, _dependencies):
            self.calls += 1
            raise TimeoutError("temporary provider timeout")

    adapter = TimeoutAdapter()
    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-write-step-no-recovery",
            "steps": [
                {
                    "step_id": "add-1",
                    "type": "add_fields",
                    "field_name": "custom_field",
                    "field_value": "fixed",
                    "config_ref": "session.decoded_config",
                }
            ],
        }
    )

    report = asyncio.run(
        create_plan_executor({"add_fields": adapter}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(decoded_data={"normalize": []}),
                session_facts=SessionFacts(
                    has_decoded_config=True,
                    available_config_refs=("session.decoded_config",),
                ),
            ),
        )
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].recovered is False
    assert adapter.calls == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (TimeoutError(), True),
        (ConnectionError(), True),
        (type("RateLimitError", (Exception,), {})(), True),
        (type("Http429", (Exception,), {"status_code": 429})(), True),
        (type("Http503", (Exception,), {"status_code": 503})(), True),
        (type("Http400", (Exception,), {"status_code": 400})(), False),
        (ValueError(), False),
    ),
)
def test瞬时分类器只接受网络限流服务端与超时错误(error, expected) -> None:
    from application.recovery import is_transient

    assert is_transient(error) is expected


@pytest.mark.parametrize(
    "overrides",
    (
        {"max_per_plan": -1},
        {"max_per_plan": 3},
        {"max_per_step": 2},
        {"max_rederive": 2},
    ),
)
def test恢复预算不能越过架构决策的硬上限(overrides) -> None:
    from application.recovery import RecoveryBudget

    with pytest.raises(ValueError):
        RecoveryBudget(**overrides)
