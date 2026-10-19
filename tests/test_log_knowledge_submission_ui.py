"""日志知识申请按钮与就地反馈状态测试。"""

import asyncio
from types import SimpleNamespace

from contracts.planner_models import (
    ExecutionReport,
    LogClassificationArtifact,
    LogKnowledgeSubmissionArtifact,
    StepResult,
    StepStatus,
)

from factories import make_session_state


def _classification_report(eligible):
    return ExecutionReport(
        plan_id="log",
        results=(
            StepResult(
                step_id="log",
                operation_type="log_parse",
                status=StepStatus.SUCCESS,
                artifact=LogClassificationArtifact(
                    classification={"status": "SUCCESS"},
                    item_count=1,
                    submission_eligible=eligible,
                    submission_token="snapshot-1" if eligible else None,
                ),
            ),
        ),
    )


def test申请按钮只在eligible出现且始终位于操作区末尾():
    import web.plan_renderer as renderer

    eligible = renderer._build_result_actions(_classification_report(True))
    ineligible = renderer._build_result_actions(_classification_report(False))

    assert [action.name for action in eligible] == [
        "apply_field_mapping",
        "export_rules",
        "export_sub_rules",
        "submit_log_knowledge",
    ]
    assert [action.name for action in ineligible] == [
        "apply_field_mapping",
        "export_rules",
        "export_sub_rules",
    ]


def test提交终态使用稳定就地文案且不包含原始日志():
    from web.plan_renderer import build_execution_report_content

    for status, marker in (
        ("created", "已提交"),
        ("pending_duplicate", "审核中"),
        ("already_approved", "已批准"),
        ("stale", "已变化"),
        ("error", "不受影响"),
    ):
        message = {
            "created": "日志知识申请已提交，等待管理员审核",
            "pending_duplicate": "相同日志知识申请已在审核中，已补充去重样例",
            "already_approved": "相同日志知识已批准，无需重复申请",
            "stale": "当前主数据或分类结果已变化，请重新执行日志类型提取后再申请",
            "error": "日志知识申请暂时无法提交；现有分类结果不受影响",
        }[status]
        report = ExecutionReport(
            plan_id="submit",
            results=(
                StepResult(
                    step_id="submit",
                    operation_type="log_knowledge_submit",
                    status=(
                        StepStatus.FAILED
                        if status in {"stale", "error"}
                        else StepStatus.SUCCESS
                    ),
                    artifact=LogKnowledgeSubmissionArtifact(
                        submission_status=status,
                        application_id=7 if status not in {"stale", "error"} else None,
                        item_count=1,
                    ),
                    message=message,
                ),
            ),
        )
        content = build_execution_report_content(report)
        assert marker in content
        assert "kind=raw-secret" not in content
        if status in {"stale", "error"}:
            assert "❌" in content
            assert "✅" not in content
        else:
            assert "申请编号 7" in content


def test回调显示提交中并移除可点击动作后再交给统一确定性执行器(monkeypatch):
    import web.action_callbacks as callbacks
    import web.deterministic_plan as deterministic

    events = []

    class _Action:
        payload = {"submission_token": "snapshot-1"}
        forId = "report-1"

        async def remove(self):
            events.append("removed")

        async def send(self, for_id):
            assert for_id == "report-1"
            events.append("restored")

    class _Message:
        def __init__(self, *, content):
            assert "提交中" in content

        async def send(self):
            events.append("submitting-shown")
            return self

        async def remove(self):
            events.append("submitting-removed")

    session = make_session_state(team=object())
    monkeypatch.setattr(
        callbacks.cl,
        "user_session",
        SimpleNamespace(get=lambda key: session if key == "user_session" else None),
    )
    monkeypatch.setattr(callbacks.cl, "Message", _Message)

    async def execute(**kwargs):
        assert kwargs["steps"][0].submission_token == "snapshot-1"
        events.append((kwargs["plan_id"], kwargs["steps"][0].type))
        return ExecutionReport(
            plan_id=kwargs["plan_id"],
            results=(
                StepResult(
                    step_id="submit-log-knowledge",
                    operation_type="log_knowledge_submit",
                    status=StepStatus.SUCCESS,
                    artifact=LogKnowledgeSubmissionArtifact(
                        submission_status="created",
                        application_id=7,
                        item_count=1,
                    ),
                ),
            ),
        )

    monkeypatch.setattr(deterministic, "execute_deterministic_plan", execute)

    asyncio.run(callbacks.on_submit_log_knowledge(_Action()))

    assert events == [
        "removed",
        "submitting-shown",
        ("button-submit-log-knowledge", "log_knowledge_submit"),
        "submitting-removed",
    ]


def test仓储错误后恢复申请按钮而过期结果不恢复(monkeypatch):
    import web.action_callbacks as callbacks
    import web.deterministic_plan as deterministic

    async def run(status):
        events = []

        class _Action:
            payload = {"submission_token": "snapshot-1"}
            forId = "report-1"

            async def remove(self):
                events.append("removed")

            async def send(self, for_id):
                assert for_id == "report-1"
                events.append("restored")

        class _Message:
            def __init__(self, *, content):
                pass

            async def send(self):
                return self

            async def remove(self):
                events.append("submitting-removed")

        monkeypatch.setattr(callbacks.cl, "Message", _Message)

        async def execute(**kwargs):
            return ExecutionReport(
                plan_id=kwargs["plan_id"],
                results=(
                    StepResult(
                        step_id="submit-log-knowledge",
                        operation_type="log_knowledge_submit",
                        status=StepStatus.FAILED,
                        artifact=LogKnowledgeSubmissionArtifact(
                            submission_status=status,
                            item_count=0,
                        ),
                        error_code=f"log_knowledge_submission_{status}",
                        message=status,
                    ),
                ),
            )

        monkeypatch.setattr(deterministic, "execute_deterministic_plan", execute)
        await callbacks.on_submit_log_knowledge(_Action())
        return events

    session = make_session_state(team=object())
    monkeypatch.setattr(
        callbacks.cl,
        "user_session",
        SimpleNamespace(get=lambda key: session if key == "user_session" else None),
    )

    assert asyncio.run(run("error")) == [
        "removed",
        "submitting-removed",
        "restored",
    ]
    assert asyncio.run(run("stale")) == ["removed", "submitting-removed"]
