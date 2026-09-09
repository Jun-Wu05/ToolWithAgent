"""Issue #143: public Application request runtime tracer tests."""

from __future__ import annotations

import asyncio


def test_natural_language_request_plans_once_and_executes_typed_plan() -> None:
    """One public call owns facts, Planner, execution and session history."""
    from application.request_runtime import run_user_request
    from application.session_state import SessionState
    from contracts.planner_models import PlanDecision, StepStatus

    class Planner:
        def __init__(self) -> None:
            self.calls = 0

        async def plan(self, **kwargs):
            self.calls += 1
            assert kwargs["conversation_history"] == []
            assert kwargs["session_facts"].has_decoded_config is True
            return PlanDecision.model_validate(
                {
                    "decision": "execute",
                    "plan_id": "request-runtime",
                    "steps": [
                        {
                            "step_id": "export",
                            "type": "export",
                            "source_ref": "session.decoded_config",
                        }
                    ],
                }
            )

    class Sink:
        def __init__(self) -> None:
            self.events = []

        async def publish(self, event) -> None:
            self.events.append(event)

    planner = Planner()
    sink = Sink()
    session = SessionState(
        decoded_data={"normalize": [{"index": "src", "field": "源IP"}]}
    )
    result = asyncio.run(
        run_user_request(
            session=session,
            team=None,
            user_text="导出当前配置",
            progress_sink=sink,
            progress_plan_id="request-progress",
            planner=planner,
        )
    )

    assert planner.calls == 1
    assert result.status == StepStatus.SUCCESS
    assert result.results[0].artifact.download_kind == "current_config"
    assert session.conversation_history == [
        {"role": "user", "content": "导出当前配置"},
        {"role": "assistant", "content": "已执行：导出配置（成功）。"},
    ]
    assert [event.message_code for event in sink.events] == [
        "planner_understanding",
        "plan_execution_started",
        "export_started",
        "export_completed",
        "plan_success",
    ]


def test上一轮助手方案进入下一次planner历史() -> None:
    """唯一方案的确认续接必须能看到上一轮助手追问，而不只有用户消息。"""
    from application.request_runtime import run_user_request
    from application.session_state import SessionState
    from contracts.planner_models import PlanDecision

    class Planner:
        def __init__(self) -> None:
            self.histories = []

        async def plan(self, **kwargs):
            self.histories.append(kwargs["conversation_history"])
            if len(self.histories) == 1:
                return PlanDecision(
                    decision="clarification",
                    plan_id="proposal",
                    reason_code="confirm_threat_chain",
                    question="将提取 event_str 的值并映射、填充到威胁类型，是否执行？",
                    choices=("确认执行", "取消"),
                )
            return PlanDecision(decision="guidance", guidance_code="done")

    class Sink:
        async def publish(self, event) -> None:
            pass

    planner = Planner()
    session = SessionState()
    for user_text in ("把event_str映射为威胁类型", "确认"):
        asyncio.run(
            run_user_request(
                session=session,
                team=None,
                user_text=user_text,
                progress_sink=Sink(),
                progress_plan_id="history-test",
                planner=planner,
            )
        )

    assert planner.histories[0] == []
    assert [turn.model_dump() for turn in planner.histories[1]] == [
        {"role": "user", "content": "把event_str映射为威胁类型"},
        {
            "role": "assistant",
            "content": (
                "将提取 event_str 的值并映射、填充到威胁类型，是否执行？"
                " 可选：确认执行；取消"
            ),
        },
    ]


def test显式威胁来源计划按当前配置编译为原子替换链(monkeypatch) -> None:
    """Planner 只给语义四步时，运行时按已有威胁类型确定性补删除步骤。"""
    from application import request_runtime
    from application.session_state import SessionState
    from contracts.planner_models import ExecutionReport, PlanDecision

    class Planner:
        async def plan(self, **_kwargs):
            return PlanDecision.model_validate(
                {
                    "decision": "execute",
                    "plan_id": "explicit-alarm-name",
                    "steps": [
                        {
                            "step_id": "enum-1",
                            "type": "enum_extract",
                            "target_field": "alarm_name",
                            "source_ref": "session.logs",
                        },
                        {
                            "step_id": "threat-1",
                            "type": "threat_mapping",
                            "source_ref": "step:enum-1",
                            "depends_on": ["enum-1"],
                        },
                        {
                            "step_id": "add-1",
                            "type": "add_fields",
                            "field_name": "威胁类型",
                            "field_value": "%{alarm_name}",
                            "value_type": "reference",
                            "rule_group": "threat",
                            "config_ref": "session.mapped_sub_rules",
                            "depends_on": ["threat-1"],
                        },
                        {
                            "step_id": "fill-1",
                            "type": "fill",
                            "fill_kind": "threat",
                            "target_fields": ["威胁类型"],
                            "source_ref": "step:threat-1",
                            "config_ref": "session.mapped_sub_rules",
                            "depends_on": ["threat-1"],
                        },
                    ],
                }
            )

    class Sink:
        async def publish(self, _event):
            pass

    captured = {}

    async def capture_execution(*, plan, **_kwargs):
        captured["plan"] = plan
        return ExecutionReport(plan_id=plan.plan_id, results=())

    async def no_follow_up(*, report, **_kwargs):
        return report

    monkeypatch.setattr(
        request_runtime, "_execute_plan_with_threat_transaction", capture_execution
    )
    monkeypatch.setattr(
        request_runtime, "run_threat_chain_after_mapping", no_follow_up
    )
    session = SessionState(
        raw_log_lines=["alarm_name=scan"],
        mapped_sub_rules=[
            {
                "name": "threat-rule",
                "normalize": [
                    {"index": "alarm_name", "result": ["scan"]},
                    {"index": "威胁类型", "mappings": []},
                ],
                "parser": {
                    "filter": [
                        {
                            "name": "addFields",
                            "id": "",
                            "fields": {
                                "事件名称": "网络攻击",
                                "事件级别": "提醒",
                                "威胁类型": "其他",
                            },
                        }
                    ]
                },
            }
        ],
    )

    asyncio.run(
        request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="把 alarm_name 映射为威胁类型",
            progress_sink=Sink(),
            progress_plan_id="explicit-alarm-name",
            planner=Planner(),
        )
    )

    plan = captured["plan"]
    assert [step.type for step in plan.steps] == [
        "enum_extract",
        "threat_mapping",
        "delete_fields",
        "add_fields",
        "fill",
    ]
    assert plan.steps[0].target_field == "alarm_name"
    assert plan.steps[3].field_value == "%{alarm_name}"
