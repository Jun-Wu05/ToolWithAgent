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
