"""Issue #135：Application 字段映射与事件名称标注链路契约。"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace


def _import_roots(path: Path) -> set[str]:
    """提取模块的静态导入根，用于约束 Application 不反向依赖 Web。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_application_field_mapping_chain_has_no_web_or_chainlit_dependency() -> None:
    """字段映射模块可进入领域实现，但不得反向依赖 Web 或 Chainlit。"""
    root = Path(__file__).parents[1]
    violations = {}
    for relative in (
        "application/adapters/field_mapping.py",
        "application/field_mapping_batch.py",
        "application/field_mapping_input.py",
        "application/field_source.py",
        "application/parsing.py",
    ):
        path = root / relative
        if not path.exists():
            violations[relative] = ["missing"]
            continue
        forbidden = _import_roots(path) & {"web", "chainlit"}
        if forbidden:
            violations[relative] = sorted(forbidden)

    assert violations == {}


def test_field_mapping_adapter_no_longer_owns_batch_loop() -> None:
    """Adapter 接口不再泄漏任务创建、Semaphore 或补查实现。"""
    source = (
        Path(__file__).parents[1] / "application/adapters/field_mapping.py"
    ).read_text(encoding="utf-8")

    assert "asyncio.create_task" not in source
    assert "asyncio.Semaphore" not in source
    assert "_backfill_field_mapping_rows" not in source


def test_legacy_field_mapping_paths_reexport_identical_application_objects() -> None:
    """迁移期旧路径只重导出同一对象，不保留第二份实现。"""
    from application.adapters.field_mapping import (
        FieldMappingAdapter,
        FieldMappingBatchError,
        FieldMappingExecutionPolicy,
    )
    from application.field_mapping_input import build_batch_llm_input
    from application.field_source import extract_log_fields_for_mapping
    from application.parsing import parse_json_mapping_result
    from web.adapters.field_mapping import (
        FieldMappingAdapter as LegacyAdapter,
        FieldMappingBatchError as LegacyBatchError,
        FieldMappingExecutionPolicy as LegacyPolicy,
    )
    from web.field_source import extract_log_fields_for_mapping as legacy_field_source
    from web.input_builder import build_batch_llm_input as legacy_input_builder
    from web.parsers import parse_json_mapping_result as legacy_parser

    assert LegacyAdapter is FieldMappingAdapter
    assert LegacyBatchError is FieldMappingBatchError
    assert LegacyPolicy is FieldMappingExecutionPolicy
    assert legacy_field_source is extract_log_fields_for_mapping
    assert legacy_input_builder is build_batch_llm_input
    assert legacy_parser is parse_json_mapping_result


def test_default_composition_uses_application_field_mapping_adapter() -> None:
    """唯一生产组合入口直接注册 Application 字段映射适配器。"""
    from application.adapters.field_mapping import FieldMappingAdapter
    from web.adapters import create_default_adapters

    assert isinstance(create_default_adapters(None)["field_mapping"], FieldMappingAdapter)


def test_field_mapping_prompt_contents_and_missing_policy_are_unchanged(monkeypatch) -> None:
    """字段映射 Prompt 仍从 Prompt 包逐字加载，缺失时继续立即失败。"""
    import agent.prompts as prompts

    prompt_dir = Path(prompts.__file__).parent
    expected = {
        "load_field_weak_prompt": "field_weak.md",
        "load_field_strong_prompt": "field_strong.md",
    }
    for function_name, filename in expected.items():
        assert getattr(prompts, function_name)() == (prompt_dir / filename).read_text(
            encoding="utf-8"
        )

    monkeypatch.setattr(prompts, "__file__", str(prompt_dir / "missing" / "__init__.py"))
    for function_name in expected:
        try:
            getattr(prompts, function_name)()
        except FileNotFoundError as error:
            assert expected[function_name] in str(error)
        else:
            raise AssertionError("字段映射 Prompt 缺失时应保持立即失败策略")


def test_field_mapping_tracer_preserves_calls_order_and_session_commit() -> None:
    """公共适配器接缝保持字段顺序、调用次数与成功后一次性提交语义。"""
    from application.adapters.field_mapping import FieldMappingAdapter
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_projection import build_session_facts
    from contracts.planner_models import FieldMappingStep, PlanDecision, StepStatus

    class MappingMember:
        name = "FieldMappingAgent"

        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        async def arun(self, model_input, *, stream, stream_events):
            marker = "字段列表（第 1/1 批，共 2 个字段）：\n"
            fields = tuple(json.loads(model_input.split(marker, 1)[1].split("\n", 1)[0]))
            self.calls.append(fields)
            rows = [
                {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
                for field in reversed(fields)
            ]
            yield SimpleNamespace(event="RunCompleted", content=rows)

    member = MappingMember()
    session = {"decoded_fields": ["src", "dst"]}
    step = FieldMappingStep(
        step_id="mapping-1", type="field_mapping", source_ref="session.fields"
    )
    report = asyncio.run(
        PlanExecutor(
            {
                "field_mapping": FieldMappingAdapter(
                    SimpleNamespace(members=[member]),
                    candidate_retriever=lambda fields: "",
                )
            }
        ).execute(
            PlanDecision(decision="execute", plan_id="mapping-tracer", steps=(step,)),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert member.calls == [("src", "dst")]
    assert [row.original_field for row in report.results[0].artifact.mappings] == ["src", "dst"]
    assert [row["原始字段名"] for row in session["last_mapping_data"]] == ["src", "dst"]
