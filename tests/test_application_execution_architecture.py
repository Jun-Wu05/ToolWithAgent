"""Issue #133: Application execution runtime and export tracer contracts."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_application_runtime_core_has_no_ui_or_domain_dependencies() -> None:
    """执行、会话和进度核心只能依赖 Contracts、Application 核心与标准库。"""
    root = Path(__file__).parents[1]
    forbidden = {"agent", "agno", "chainlit", "web"}
    violations = {
        relative: sorted(_import_roots(root / relative) & forbidden)
        for relative in (
            "application/execution.py",
            "application/progress.py",
            "application/session_state.py",
        )
        if (root / relative).exists()
        and _import_roots(root / relative) & forbidden
    }

    assert violations == {}


def test_legacy_runtime_paths_are_deleted() -> None:
    """Completed migration removes the temporary Web runtime paths."""
    root = Path(__file__).parents[1]
    for relative in (
        "web/plan_executor.py",
        "web/session_state.py",
        "web/execution_adapters.py",
    ):
        assert not (root / relative).exists()
    assert not any((root / "web/adapters").glob("*.py"))


def test_export_tracer_runs_through_application_without_mutating_session() -> None:
    """导出 tracer 保持 ExecutionReport、进度、Base64 字节与下载语义。"""
    from application.adapters.export import ExportAdapter
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_state import SessionState
    from application.session_projection import build_session_facts
    from contracts.planner_models import ExportStep, PlanDecision, StepStatus

    class RecordingProgressSink:
        def __init__(self) -> None:
            self.events = []

        async def publish(self, event) -> None:
            self.events.append(event)

    config = {"normalize": [{"index": "src", "field": "源IP"}]}
    session = SessionState(decoded_data=config)
    before = session.decoded_data.copy()
    sink = RecordingProgressSink()
    step = ExportStep(
        step_id="export-1", type="export", source_ref="session.decoded_config"
    )
    plan = PlanDecision(decision="execute", plan_id="export-tracer", steps=(step,))

    report = asyncio.run(
        PlanExecutor({"export": ExportAdapter()}).execute(
            plan,
            ExecutionContext(
                session=session,
                session_facts=build_session_facts(session),
                progress_sink=sink,
            ),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert report.results[0].artifact.content == (
        "eyJub3JtYWxpemUiOiBbeyJpbmRleCI6ICJzcmMiLCAiZmllbGQiOiAi5rqQSVAifV19"
    )
    assert report.results[0].artifact.download_kind == "current_config"
    assert session.decoded_data == before
    assert [event.message_code for event in sink.events] == [
        "plan_execution_started",
        "export_started",
        "export_completed",
        "plan_success",
    ]


def test_export_tracer_preserves_missing_and_stale_source_errors() -> None:
    """Application 导出接缝继续失败关闭并返回稳定 needs_input 错误码。"""
    from application.adapters.export import ExportAdapter
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_state import SessionState
    from application.session_projection import build_session_facts
    from contracts.planner_models import ExportStep, PlanDecision, StepStatus

    async def execute(session: SessionState, source_ref: str):
        step = ExportStep(step_id="export-1", type="export", source_ref=source_ref)
        return await PlanExecutor({"export": ExportAdapter()}).execute(
            PlanDecision(decision="execute", plan_id="export-tracer", steps=(step,)),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )

    missing = asyncio.run(execute(SessionState(), "session.decoded_config"))
    assert missing.status == StepStatus.NEEDS_INPUT
    assert missing.results[0].error_code == "config_source_unavailable"

    stale_session = SessionState(
        decoded_data={"normalize": [{"index": "src", "field": "源IP"}]},
        stale_enum_config_refs={"session.decoded_config"},
    )
    stale = asyncio.run(execute(stale_session, "session.decoded_config"))
    assert stale.status == StepStatus.NEEDS_INPUT
    assert stale.results[0].error_code == "enum_refill_required"


def test_planner_typed_sub_rule_export_cannot_bypass_mapped_rule_guard() -> None:
    """自然语言 Planner 产出的同一 source_ref 必须在执行接缝被统一拦截。"""
    from application.adapters.export import ExportAdapter
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_state import SessionState
    from application.session_projection import build_session_facts
    from contracts.planner_models import ExportStep, PlanDecision, StepStatus

    session = SessionState(
        log_classification={"types": ["AUDIT"]},
        mapped_sub_rules=[
            {
                "name": "AUDIT",
                "normalize": [{"index": "event", "field": "事件名称"}],
            }
        ],
    )
    step = ExportStep(
        step_id="export-sub",
        type="export",
        source_ref="session.log_classification.sub_rules",
    )

    report = asyncio.run(
        PlanExecutor({"export": ExportAdapter()}).execute(
            PlanDecision(decision="execute", plan_id="planner-export", steps=(step,)),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "mapped_sub_rules_present"
    assert "生成映射后子规则" in report.results[0].message
