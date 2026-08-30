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
        {"role": "user", "content": "导出当前配置"}
    ]
    assert [event.message_code for event in sink.events] == [
        "planner_understanding",
        "plan_execution_started",
        "export_started",
        "export_completed",
        "plan_success",
    ]
