"""Issue #143: public Application request runtime tracer tests."""

from __future__ import annotations

import asyncio


def test_natural_language_request_plans_once_and_executes_typed_plan() -> None:
    """One public call owns facts, Planner, execution and session history."""
    from application.request_runtime import run_user_request
    from factories import make_session_state
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
    session = make_session_state(
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
    from factories import make_session_state
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
    session = make_session_state()
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
    from factories import make_session_state
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
    session = make_session_state(
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


def test自动选择跳过无有效映射并只提交成功候选(monkeypatch) -> None:
    """候选试跑隔离：全兜底结果不提交，下一有效来源才写回。"""
    from application import request_runtime
    from factories import make_session_state
    from contracts.planner_models import (
        ExecutionReport,
        PlanDecision,
        StepResult,
        StepStatus,
        ThreatMappingArtifact,
        ThreatMappingRow,
    )

    class Planner:
        async def plan(self, **_kwargs):
            return PlanDecision(
                decision="clarification",
                plan_id="auto-source",
                reason_code="threat_source_auto_requested",
                question="placeholder",
            )

    class Sink:
        async def publish(self, _event):
            pass

    monkeypatch.setattr(
        request_runtime,
        "rank_threat_source_candidates",
        lambda _fields: ("threat_type", "alarm_name", "event_type1"),
    )
    attempts = []

    async def execute_candidate(*, session, plan, **_kwargs):
        source = plan.steps[0].target_field
        attempts.append(source)
        session.mapped_sub_rules[0]["selected"] = source
        mapped_value = "其他" if source == "threat_type" else "网络扫描"
        return ExecutionReport(
            plan_id=plan.plan_id,
            results=(
                StepResult(
                    step_id="threat-chain-map",
                    operation_type="threat_mapping",
                    status=StepStatus.SUCCESS,
                    artifact=ThreatMappingArtifact(
                        mappings=(
                            ThreatMappingRow(
                                mappingType="REGULAR",
                                orgValue=".*",
                                mappingValue=mapped_value,
                            ),
                        ),
                        source_field=source,
                        item_count=1,
                    ),
                ),
                StepResult(
                    step_id="threat-chain-fill",
                    operation_type="fill",
                    status=StepStatus.SUCCESS,
                    changed_count=1,
                ),
                StepResult(
                    step_id="threat-chain-add",
                    operation_type="add_fields",
                    status=StepStatus.SUCCESS,
                    changed_count=1,
                ),
            ),
        )

    monkeypatch.setattr(
        request_runtime, "_execute_plan_with_threat_transaction", execute_candidate
    )
    session = make_session_state(
        raw_log_lines=["alarm_name=scan threat_type=1002"],
        mapped_sub_rules=[
            {
                "name": "threat-rule",
                "normalize": [
                    {"index": "alarm_name", "result": ["scan"]},
                    {"index": "event_type1", "result": ["scan"]},
                    {"index": "threat_type", "result": ["1002"]},
                ],
                "parser": {
                    "filter": [
                        {
                            "name": "addFields",
                            "id": "",
                            "fields": {"事件名称": "网络攻击", "事件级别": "提醒"},
                        }
                    ]
                },
            }
        ],
    )

    result = asyncio.run(
        request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="请为威胁类型选择合适的来源字段",
            progress_sink=Sink(),
            progress_plan_id="auto-source",
            planner=Planner(),
        )
    )

    assert attempts == ["threat_type", "alarm_name"]
    assert result.status == StepStatus.SUCCESS
    assert session.mapped_sub_rules[0]["selected"] == "alarm_name"
    assert session.threat_source_field_override == "alarm_name"


def _export_proposal():
    from contracts.planner_models import PlanDecision

    return PlanDecision.model_validate(
        {
            "decision": "proposal",
            "plan_id": "proposal-export",
            "reason_code": "confirmation_required",
            "question": "将导出当前配置，是否执行？",
            "choices": ["确认执行", "取消"],
            "steps": [
                {
                    "step_id": "export-1",
                    "type": "export",
                    "source_ref": "session.decoded_config",
                }
            ],
        }
    )


def test提案保存后确认同一计划且只能执行一次(monkeypatch) -> None:
    from application import request_runtime
    from factories import make_session_state
    from contracts.planner_models import ExecutionReport, PlanDecision

    class Planner:
        def __init__(self):
            self.calls = 0

        async def plan(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                assert kwargs["pending_plan"] is None
                return _export_proposal()
            pending = kwargs["pending_plan"]
            return PlanDecision(
                decision="confirm",
                plan_id=f"confirm-{self.calls}",
                pending_plan_id=(pending.plan_id if pending else "proposal-export"),
            )

    class Sink:
        async def publish(self, _event):
            pass

    executed = []

    async def capture_execution(*, plan, **_kwargs):
        executed.append(plan)
        return ExecutionReport(plan_id=plan.plan_id, results=())

    async def no_follow_up(*, report, **_kwargs):
        return report

    monkeypatch.setattr(
        request_runtime, "_execute_plan_with_threat_transaction", capture_execution
    )
    monkeypatch.setattr(request_runtime, "run_threat_chain_after_mapping", no_follow_up)
    planner = Planner()
    session = make_session_state(decoded_data={"normalize": []})

    proposal = asyncio.run(
        request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="先给方案",
            progress_sink=Sink(),
            progress_plan_id="proposal",
            planner=planner,
        )
    )
    proposal_execution = session.current_execution
    confirmed = asyncio.run(
        request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="确认执行",
            progress_sink=Sink(),
            progress_plan_id="confirm",
            planner=planner,
        )
    )
    repeated = asyncio.run(
        request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="再次确认",
            progress_sink=Sink(),
            progress_plan_id="confirm-again",
            planner=planner,
        )
    )

    assert proposal.decision == "proposal"
    assert proposal_execution is None
    assert confirmed.plan_id == "proposal-export"
    assert [plan.plan_id for plan in executed] == ["proposal-export"]
    assert repeated.reason_code == "pending_plan_not_found"
    assert session.current_execution.plan_id == "proposal-export"
    assert session.pending_plan is None


def test取消和事实变化均不执行待确认计划(monkeypatch) -> None:
    from application import request_runtime
    from factories import make_session_state
    from contracts.planner_models import PlanDecision

    class Sink:
        async def publish(self, _event):
            pass

    async def should_not_execute(**_kwargs):
        raise AssertionError("待确认计划不得执行")

    monkeypatch.setattr(
        request_runtime, "_execute_plan_with_threat_transaction", should_not_execute
    )

    async def run_case(control: str, mutate: bool = False):
        calls = 0

        class Planner:
            async def plan(self, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return _export_proposal()
                return PlanDecision(
                    decision=control,
                    plan_id=f"{control}-export",
                    pending_plan_id=kwargs["pending_plan"].plan_id,
                )

        session = make_session_state(decoded_data={"normalize": []})
        planner = Planner()
        await request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="先给方案",
            progress_sink=Sink(),
            progress_plan_id="proposal",
            planner=planner,
        )
        if mutate:
            session.decoded_data["normalize"].append(
                {"index": "src", "field": "源IP", "mappings": []}
            )
        result = await request_runtime.run_user_request(
            session=session,
            team=None,
            user_text=control,
            progress_sink=Sink(),
            progress_plan_id=control,
            planner=planner,
        )
        return result, session

    cancelled, cancelled_session = asyncio.run(run_case("cancel"))
    stale, stale_session = asyncio.run(run_case("confirm", mutate=True))

    assert cancelled.guidance_code == "pending_plan_cancelled"
    assert cancelled_session.current_execution is None
    assert cancelled_session.pending_plan is None
    assert stale.reason_code == "pending_plan_stale"
    assert stale_session.current_execution is None
    assert stale_session.pending_plan is None
