"""Issue #223: 最近执行摘要的安全投影与生命周期。"""

import asyncio


def test空执行摘要不改变既有Planner输入形状() -> None:
    from agent.core.planner import build_planner_input
    from contracts.session_facts import SessionFacts

    planner_input = build_planner_input("下一步", (), SessionFacts())

    assert '"recent_execution"' not in planner_input


def test执行报告只投影安全步骤摘要() -> None:
    from application.session_projection import summarize_report
    from contracts.planner_models import (
        EnumValuesArtifact,
        ExecutionReport,
        StepResult,
        StepStatus,
    )

    report = ExecutionReport(
        plan_id="plan-safe-summary",
        results=(
            StepResult(
                step_id="enum-1",
                operation_type="enum_extract",
                status=StepStatus.SUCCESS,
                artifact=EnumValuesArtifact(
                    item_count=2,
                    values=("sensitive-a", "sensitive-b"),
                    field="event_type",
                    original_log=("secret-log",),
                ),
                message="secret-message",
            ),
            StepResult(
                step_id="fill-1",
                operation_type="fill",
                status=StepStatus.NEEDS_INPUT,
                error_code="target_field_required",
                message="secret-target",
            ),
        ),
    )

    summary = summarize_report(report)

    assert summary.model_dump(mode="json") == {
        "plan_id": "plan-safe-summary",
        "steps": [
            {
                "step_id": "enum-1",
                "type": "enum_extract",
                "status": "success",
                "error_code": None,
                "artifact_kinds": ["enum_values"],
                "artifact_count": 2,
            },
            {
                "step_id": "fill-1",
                "type": "fill",
                "status": "needs_input",
                "error_code": "target_field_required",
                "artifact_kinds": [],
                "artifact_count": 0,
            },
        ],
    }
    dumped = summary.model_dump_json()
    for sensitive_value in (
        "sensitive-a",
        "sensitive-b",
        "secret-log",
        "secret-message",
        "secret-target",
    ):
        assert sensitive_value not in dumped


def test连续计划滚动两份摘要并进入下一轮Planner输入() -> None:
    from agent.core.planner import build_planner_input
    from application.progress import NullProgressSink
    from application.request_runtime import run_deterministic_plan
    from application.session_projection import build_session_facts
    from application.session_state import SessionState
    from contracts.planner_models import PlanDecision

    session = SessionState(
        decoded_data={
            "name": "public-rule-name",
            "normalize": [
                {
                    "index": "public_field",
                    "field": "源IP",
                    "mappings": [
                        {
                            "mappingType": "EQUAL",
                            "orgValue": "secret-original-value",
                            "mappingValue": "secret-mapped-value",
                        }
                    ],
                }
            ],
        }
    )

    for number in range(1, 4):
        plan = PlanDecision.model_validate(
            {
                "decision": "execute",
                "plan_id": f"plan-{number}",
                "steps": [
                    {
                        "step_id": f"export-{number}",
                        "type": "export",
                        "source_ref": "session.decoded_config",
                    }
                ],
            }
        )
        asyncio.run(
            run_deterministic_plan(
                session=session,
                team=None,
                plan=plan,
                progress_sink=NullProgressSink(),
            )
        )

    facts = build_session_facts(session)
    planner_input = build_planner_input("下一步", (), facts)

    assert [summary.plan_id for summary in facts.recent_execution] == [
        "plan-3",
        "plan-2",
    ]
    assert '"recent_execution":[{"plan_id":"plan-3"' in planner_input
    assert "plan-1" not in planner_input
    assert "secret-original-value" not in planner_input
    assert "secret-mapped-value" not in planner_input


def test自然语言入口记录威胁链合并后的最终报告(monkeypatch) -> None:
    from application import request_runtime
    from application.progress import NullProgressSink
    from application.session_projection import build_session_facts
    from application.session_state import SessionState
    from contracts.planner_models import (
        ExecutionReport,
        PlanDecision,
        StepResult,
        StepStatus,
    )

    class Planner:
        async def plan(self, **_kwargs):
            return PlanDecision.model_validate(
                {
                    "decision": "execute",
                    "plan_id": "plan-with-chain",
                    "steps": [
                        {
                            "step_id": "export-1",
                            "type": "export",
                            "source_ref": "session.decoded_config",
                        }
                    ],
                }
            )

    async def append_chain_result(*, report, **_kwargs):
        return ExecutionReport(
            plan_id=report.plan_id,
            results=report.results
            + (
                StepResult(
                    step_id="threat-chain-summary",
                    operation_type="threat_chain",
                    status=StepStatus.SUCCESS,
                    message="secret-chain-detail",
                ),
            ),
        )

    monkeypatch.setattr(
        request_runtime,
        "run_threat_chain_after_mapping",
        append_chain_result,
    )
    session = SessionState(decoded_data={"normalize": []})

    asyncio.run(
        request_runtime.run_user_request(
            session=session,
            team=None,
            user_text="导出当前配置",
            progress_sink=NullProgressSink(),
            progress_plan_id="request-with-chain",
            planner=Planner(),
        )
    )

    facts = build_session_facts(session)
    assert [step.type for step in facts.recent_execution[0].steps] == [
        "export",
        "threat_chain",
    ]
    assert "secret-chain-detail" not in facts.model_dump_json()


def test自动威胁来源试选按完成顺序记录每个候选(monkeypatch) -> None:
    from application import request_runtime
    from application.session_projection import build_session_facts
    from application.session_state import SessionState
    from contracts.planner_models import (
        ExecutionReport,
        PlanDecision,
        StepResult,
        StepStatus,
    )
    from contracts.session_facts import SessionFacts

    monkeypatch.setattr(
        request_runtime,
        "rank_threat_source_candidates",
        lambda _fields: ("source-a", "source-b"),
    )
    monkeypatch.setattr(request_runtime, "stage_threat_chain_session", lambda session: session)

    def build_plan(_session, source_field, *, plan_id):
        return PlanDecision.model_validate(
            {
                "decision": "execute",
                "plan_id": plan_id,
                "steps": [
                    {
                        "step_id": source_field,
                        "type": "export",
                        "source_ref": "session.decoded_config",
                    }
                ],
            }
        )

    async def execute_candidate(*, plan, **_kwargs):
        position = int(plan.plan_id.rsplit("-", 1)[1])
        return ExecutionReport(
            plan_id=plan.plan_id,
            results=(
                StepResult(
                    step_id=f"candidate-{position}",
                    operation_type="threat_mapping",
                    status=(StepStatus.FAILED if position == 1 else StepStatus.SUCCESS),
                    error_code=("enum_extract_empty" if position == 1 else None),
                    message=f"secret-source-{position}",
                ),
            ),
        )

    monkeypatch.setattr(request_runtime, "build_threat_source_plan", build_plan)
    monkeypatch.setattr(
        request_runtime,
        "_execute_plan_with_threat_transaction",
        execute_candidate,
    )
    monkeypatch.setattr(
        request_runtime,
        "_has_meaningful_threat_mapping",
        lambda report: report.status == StepStatus.SUCCESS,
    )
    monkeypatch.setattr(request_runtime, "commit_threat_chain_session", lambda *_args: None)
    monkeypatch.setattr(request_runtime, "set_threat_source_override", lambda *_args: None)
    session = SessionState()

    asyncio.run(
        request_runtime._run_auto_threat_source_selection(
            session=session,
            team=None,
            session_facts=SessionFacts(threat_source_fields=("source-a", "source-b")),
        )
    )

    facts = build_session_facts(session)
    assert [summary.plan_id for summary in facts.recent_execution] == [
        "plan-threat-source-auto-2",
        "plan-threat-source-auto-1",
    ]
    assert facts.recent_execution[1].steps[0].status == StepStatus.FAILED
    assert "secret-source" not in facts.model_dump_json()


def test主数据与日志分类变化清空执行摘要且兼容字典会话() -> None:
    from application.file_input import commit_primary_dataset
    from application.request_runtime import clear_session_data
    from application.session_projection import summarize_report
    from application.session_state import (
        PrimaryDatasetSnapshot,
        SessionState,
        commit_log_classification,
    )
    from contracts.planner_models import ExecutionReport

    summary = summarize_report(ExecutionReport(plan_id="old-plan", results=()))
    session = SessionState(current_execution=summary, previous_execution=summary)

    session.replace_primary_dataset(
        PrimaryDatasetSnapshot(
            decoded_data={"normalize": []},
            decoded_fields=[],
            original_log=None,
            simplified_data={},
            decoded_text="",
            uploaded_file_name="new.txt",
            uploaded_file_time="now",
        )
    )
    assert session.current_execution is None
    assert session.previous_execution is None

    session.current_execution = summary
    session.previous_execution = summary
    commit_log_classification(session, {"type": "new"})
    assert session.current_execution is None
    assert session.previous_execution is None

    dictionary_session = {
        "current_execution": summary.model_dump(mode="json"),
        "previous_execution": summary.model_dump(mode="json"),
    }
    commit_primary_dataset(
        dictionary_session,
        PrimaryDatasetSnapshot(
            decoded_data={"normalize": []},
            decoded_fields=[],
            original_log=None,
            simplified_data={},
            decoded_text="",
            uploaded_file_name="new.txt",
            uploaded_file_time="now",
        ),
    )
    assert "current_execution" not in dictionary_session
    assert "previous_execution" not in dictionary_session

    dictionary_session.update(
        current_execution=summary.model_dump(mode="json"),
        previous_execution=summary.model_dump(mode="json"),
    )
    clear_session_data(dictionary_session)
    assert "current_execution" not in dictionary_session
    assert "previous_execution" not in dictionary_session
