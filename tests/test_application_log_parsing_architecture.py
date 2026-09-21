"""Issue #134：Application 日志解析与规则导出 tracer 契约。"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path


def _import_roots(path: Path) -> set[str]:
    """提取模块静态导入根，避免运行导入掩盖依赖方向。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_application_log_adapter_has_no_web_or_chainlit_dependency() -> None:
    """日志适配器可进入 Agent 领域实现，但不得反向依赖 Web 或 Chainlit。"""
    root = Path(__file__).parents[1]
    violations = {}
    for relative in (
        "application/adapters/log_parse.py",
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


def test_log_parse_adapter_preserves_call_order_session_and_progress() -> None:
    """公共适配器接缝冻结格式识别、分类、样本回填与会话提交顺序。"""
    from application.adapters.log_parse import LogParseAdapter
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_projection import build_session_facts
    from contracts.planner_models import LogParseStep, PlanDecision, StepStatus

    calls = []

    def identify(logs_text: str) -> str:
        calls.append(("identify", logs_text))
        return json.dumps(
            {
                "format": "kv",
                "format_detail": "键值日志",
                "feature_field": "auto_type",
                "header_end_marker": "",
            },
            ensure_ascii=False,
        )

    def classify(*args, **kwargs) -> str:
        calls.append(("classify", args, kwargs))
        return json.dumps(
            {"classification_details": [{"logtype": "attack", "sample": "占位"}]},
            ensure_ascii=False,
        )

    def fill(classification: dict, logs_text: str) -> dict:
        calls.append(("fill", classification, logs_text))
        result = dict(classification)
        result["classification_details"] = [
            {"logtype": "attack", "real_samples": logs_text.splitlines()[0]}
        ]
        return result

    class RecordingSink:
        def __init__(self) -> None:
            self.events = []

        async def publish(self, event) -> None:
            self.events.append(event)

    session = {"raw_log_lines": ["kind=attack src=1", "kind=scan src=2"]}
    sink = RecordingSink()
    step = LogParseStep(step_id="log-1", type="log_parse", feature_field="kind")
    report = asyncio.run(
        PlanExecutor(
            {
                "log_parse": LogParseAdapter(
                    format_identifier=identify,
                    classifier=classify,
                    sample_filler=fill,
                )
            }
        ).execute(
            PlanDecision(decision="execute", plan_id="log-tracer", steps=(step,)),
            ExecutionContext(
                session=session,
                session_facts=build_session_facts(session),
                progress_sink=sink,
            ),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert [call[0] for call in calls] == ["identify", "classify", "fill"]
    classify_args = calls[1][1]
    classify_kwargs = calls[1][2]
    assert classify_args[:4] == (
        "kind=attack src=1\nkind=scan src=2",
        "kv",
        "键值日志",
        "kind",
    )
    assert classify_kwargs == {"feature_field_explicit": True}
    assert session["log_classification"] == report.results[0].artifact.classification
    assert report.results[0].artifact.item_count == 1
    assert [event.message_code for event in sink.events] == [
        "plan_execution_started",
        "log_parse_started",
        "log_parse_completed",
        "plan_success",
    ]


def test日志解析只生成提交资格快照且不会写知识库() -> None:
    """正常分类成功路径只提交会话快照，显式按钮前不得触碰 SQLite。"""
    from application.adapters.log_parse import LogParseAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import LogParseStep

    lines = ["kind=a src=1", "kind=b src=2", "kind=c src=3"]
    session = {"raw_log_lines": lines}
    classification = {
        "status": "SUCCESS",
        "log_format": "kv",
        "log_format_detail": "KV",
        "feature_field": "kind",
        "coverage": {"total_lines": 3, "matched_lines": 3},
        "classification_details": [{"logtype": "a", "count": 1}],
        "analysis": {"delimit": " ", "tab": "="},
    }

    result = asyncio.run(
        LogParseAdapter(
            format_identifier=lambda _: '{"format":"kv","feature_field":"kind"}',
            classifier=lambda *args, **kwargs: json.dumps(classification),
            sample_filler=lambda value, _: value,
        ).execute(
            LogParseStep(step_id="log", type="log_parse"),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status.value == "success"
    assert session["log_knowledge_submission"].eligible is True
    assert "log_knowledge_application" not in session


def test重新提取日志类型原子清理映射派生状态并释放白板导出gate(monkeypatch) -> None:
    """新分类不得与旧映射、事件标注、手动调整或其枚举账本混用。"""
    import agent.tools.rule_generator as rule_generator

    from application.adapters.export import ExportAdapter
    from application.adapters.log_parse import LogParseAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import ExportStep, LogParseStep, StepStatus

    mapped_ref = "session.mapped_sub_rules"
    decoded_ref = "session.decoded_config"
    session = {
        "raw_log_lines": ["kind=new src=1"],
        "decoded_data": {"name": "uploaded", "normalize": []},
        "log_classification": {"classification_details": [{"logtype": "old"}]},
        "mapped_sub_rules": [
            {
                "name": "old",
                "normalize": [{"index": "kind", "field": "事件名称"}],
            }
        ],
        "sub_rule_mapping_results": [{"rule_name": "old"}],
        "last_mapping_data": [{"原始字段名": "kind"}],
        "excel_data": b"old-workbook",
        "excel_filename": "old.xlsx",
        "enum_fill_contributions": {
            mapped_ref: {"kind": [{"orgValue": "old"}]},
            decoded_ref: {"severity": [{"orgValue": "high"}]},
        },
        "stale_enum_config_refs": {mapped_ref, decoded_ref},
        "enum_pending_refills": {
            mapped_ref: {"kind"},
            decoded_ref: {"severity"},
        },
        "rule_source_fields": {
            "product": "旧产品",
            "log_vendor": "旧厂商",
            "data_source": "旧来源",
        },
        "pending_rule_source_step": ExportStep(
            step_id="old-export",
            type="export",
            source_ref="session.log_classification.entry_rules",
        ),
    }
    classification = {
        "classification_details": [{"logtype": "new", "sample": "kind=new src=1"}]
    }

    result = asyncio.run(
        LogParseAdapter(
            format_identifier=lambda _: '{"format":"kv","feature_field":"kind"}',
            classifier=lambda *args, **kwargs: json.dumps(
                classification, ensure_ascii=False
            ),
            sample_filler=lambda value, _: value,
        ).execute(
            LogParseStep(step_id="reparse", type="log_parse"),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert session["log_classification"] == classification
    for key in (
        "mapped_sub_rules",
        "sub_rule_mapping_results",
        "last_mapping_data",
        "excel_data",
        "excel_filename",
    ):
        assert session[key] is None
    assert session["enum_fill_contributions"] == {
        decoded_ref: {"severity": [{"orgValue": "high"}]}
    }
    assert session["stale_enum_config_refs"] == {decoded_ref}
    assert session["enum_pending_refills"] == {decoded_ref: {"severity"}}
    assert session["rule_source_fields"] is None
    assert session["pending_rule_source_step"] is None
    assert "⚠️" in result.message
    assert "映射" in result.message
    assert "事件标注" in result.message
    assert "手动调整" in result.message

    mapped_export = asyncio.run(
        ExportAdapter().execute(
            ExportStep(
                step_id="export-mapped",
                type="export",
                source_ref=mapped_ref,
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert mapped_export.status == StepStatus.NEEDS_INPUT
    assert mapped_export.error_code == "export_source_required"

    calls = []
    monkeypatch.setattr(
        rule_generator,
        "generate_rules",
        lambda value, mode, rule_source_fields: calls.append(
            (value, mode, rule_source_fields)
        )
        or {"success": True, "rules": [{"name": "new"}]},
    )
    monkeypatch.setattr(rule_generator, "rules_to_base64_text", lambda rules: "new-rules")
    whiteboard_export = asyncio.run(
        ExportAdapter().execute(
            ExportStep(
                step_id="export-whiteboard",
                type="export",
                source_ref="session.log_classification.sub_rules",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert whiteboard_export.status == StepStatus.NEEDS_INPUT
    assert whiteboard_export.error_code == "data_source_fields_required"
    assert calls == []

    from contracts.rule_source import RuleSourceFields

    source_fields = RuleSourceFields.create(product="新产品", log_vendor="新厂商")
    session["rule_source_fields"] = source_fields
    whiteboard_export = asyncio.run(
        ExportAdapter().execute(
            ExportStep(
                step_id="export-whiteboard-after-source",
                type="export",
                source_ref="session.log_classification.sub_rules",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert whiteboard_export.status == StepStatus.SUCCESS
    assert whiteboard_export.artifact.content == "new-rules"
    assert calls == [(classification, "sub", source_fields)]


def test_log_parse_adapter_preserves_stable_errors_without_overwriting_session() -> None:
    """格式或分类 JSON 非法时失败关闭，并保留此前成功分类。"""
    from application.adapters.log_parse import LogParseAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import LogParseStep, StepStatus

    step = LogParseStep(step_id="log-1", type="log_parse")

    async def execute(adapter, session):
        return await adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )

    previous = {"classification_details": [{"logtype": "old"}]}
    invalid_session = {
        "raw_log_lines": ["kind=attack"],
        "log_classification": previous,
        "mapped_sub_rules": [{"name": "old-mapped"}],
    }
    invalid = asyncio.run(
        execute(
            LogParseAdapter(
                format_identifier=lambda _: "not-json",
                classifier=lambda *args, **kwargs: "should-not-run",
                sample_filler=lambda value, _: value,
            ),
            invalid_session,
        )
    )
    assert invalid.status == StepStatus.FAILED
    assert invalid.error_code == "log_format_invalid"
    assert invalid_session["log_classification"] is previous
    assert invalid_session["mapped_sub_rules"] == [{"name": "old-mapped"}]

    empty_session = {
        "raw_log_lines": ["kind=attack"],
        "log_classification": previous,
    }
    empty = asyncio.run(
        execute(
            LogParseAdapter(
                format_identifier=lambda _: '{"format":"kv"}',
                classifier=lambda *args, **kwargs: "{}",
                sample_filler=lambda value, _: value,
            ),
            empty_session,
        )
    )
    assert empty.status == StepStatus.FAILED
    assert empty.error_code == "log_parse_failed"
    assert empty_session["log_classification"] is previous


def test_nonempty_failed_classification_preserves_historical_success_result() -> None:
    """零行为迁移不改变非空 FAILED 分类字典仍被提交的历史语义。"""
    from application.adapters.log_parse import LogParseAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import LogParseStep, StepStatus

    session = {"raw_log_lines": ["kind=attack"]}
    result = asyncio.run(
        LogParseAdapter(
            format_identifier=lambda _: '{"format":"kv"}',
            classifier=lambda *args, **kwargs: '{"status":"FAILED","error":"历史失败结构"}',
            sample_filler=lambda value, _: value,
        ).execute(
            LogParseStep(step_id="log-1", type="log_parse"),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert session["log_classification"] == {
        "status": "FAILED",
        "error": "历史失败结构",
    }


def test_legacy_json_prompt_and_adapter_paths_reexport_identical_objects() -> None:
    """迁移期旧入口必须引用同一对象，不能保留第二份实现。"""
    import agent.prompts as legacy_prompts
    import agent.prompts as prompts
    from application.adapters.log_parse import LogParseAdapter
    from application.parsing import parse_json_safe
    from application.adapters.log_parse import LogParseAdapter as LegacyAgentOpsAdapter
    from application.adapters.log_parse import LogParseAdapter as LegacyExecutionAdapter
    from application.parsing import parse_json_safe as legacy_parse_json_safe

    prompt_names = (
        "load_log_format_identify_prompt",
        "load_log_classify_feature_prompt",
        "load_log_header_classify_prompt",
        "load_log_feature_locate_prompt",
        "load_kv_feature_identifier_prompt",
    )
    for name in prompt_names:
        assert getattr(legacy_prompts, name) is getattr(prompts, name)

    assert legacy_parse_json_safe is parse_json_safe
    assert LegacyAgentOpsAdapter is LogParseAdapter
    assert LegacyExecutionAdapter is LogParseAdapter
    assert parse_json_safe('```json\n{"key": "值"}\n```') == {"key": "值"}
    assert parse_json_safe("前缀 {\"key\": 1} 后缀") == {"key": 1}
    assert parse_json_safe("invalid") is None


def test_log_prompts_load_from_non_repository_working_directory() -> None:
    """Prompt 定位只依赖包位置，不依赖进程当前目录。"""
    root = Path(__file__).parents[1]
    script = """
import json
from agent.prompts import (
    load_kv_feature_identifier_prompt,
    load_log_classify_feature_prompt,
    load_log_feature_locate_prompt,
    load_log_format_identify_prompt,
    load_log_header_classify_prompt,
)
values = [
    load_log_format_identify_prompt(),
    load_log_classify_feature_prompt(),
    load_log_header_classify_prompt(),
    load_log_feature_locate_prompt(),
    load_kv_feature_identifier_prompt(),
]
print(json.dumps([bool(value) for value in values]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root.parent,
        env={"PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip()) == [True, True, True, True, True]


def test_log_prompt_contents_and_missing_policy_are_unchanged(monkeypatch) -> None:
    """五个 Prompt 逐字加载；资源缺失继续返回空字符串而不是抛错。"""
    import agent.prompts as prompts

    prompt_dir = Path(prompts.__file__).parent
    expected = {
        "load_log_format_identify_prompt": "log_format_identify.md",
        "load_log_classify_feature_prompt": "log_classify_feature.md",
        "load_log_header_classify_prompt": "log_header_classify.md",
        "load_log_feature_locate_prompt": "log_feature_locate.md",
        "load_kv_feature_identifier_prompt": "kv_feature_identifier.md",
    }
    for function_name, filename in expected.items():
        assert getattr(prompts, function_name)() == (prompt_dir / filename).read_text(
            encoding="utf-8"
        )

    monkeypatch.setattr(prompts, "__file__", str(prompt_dir / "missing" / "__init__.py"))
    for function_name in expected:
        assert getattr(prompts, function_name)() == ""


def test_default_composition_traces_log_classification_to_rule_export(monkeypatch) -> None:
    """唯一组合入口以跨轮事实快照贯通分类、Session 与规则 Base64。"""
    import agent.tools.pipeline.log_classifier as log_classifier
    import agent.tools.pipeline.log_format_identifier as log_format_identifier
    import agent.tools.pipeline.log_sample_filler as log_sample_filler
    import agent.tools.rule_generator as rule_generator

    from application.adapters.log_parse import LogParseAdapter
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_projection import build_session_facts
    from contracts.planner_models import PlanDecision, StepStatus
    from application.adapters import create_default_adapters

    calls = []
    classification = {
        "status": "SUCCESS",
        "classification_details": [{"logtype": "attack", "sample": "kind=attack"}],
    }
    monkeypatch.setattr(
        log_format_identifier,
        "_do_identify_log_format",
        lambda logs: (
            calls.append("identify"),
            '{"format":"kv","format_detail":"键值日志","feature_field":"kind"}',
        )[1],
    )
    monkeypatch.setattr(
        log_classifier,
        "_do_classify_log_features",
        lambda *args, **kwargs: (
            calls.append("classify"),
            json.dumps(classification, ensure_ascii=False),
        )[1],
    )
    monkeypatch.setattr(
        log_sample_filler,
        "fill_sample_logs",
        lambda value, logs: (calls.append("fill"), value)[1],
    )
    generated_rules = [{"name": "attack", "parser": {"value": "kind=(attack)"}}]
    monkeypatch.setattr(
        rule_generator,
        "generate_rules",
        lambda value, mode, rule_source_fields: (
            calls.append(("rules", value, mode, rule_source_fields)),
            {"success": True, "rules": generated_rules},
        )[1],
    )
    encoded = base64.b64encode(
        json.dumps(generated_rules, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    monkeypatch.setattr(
        rule_generator,
        "rules_to_base64_text",
        lambda rules: (calls.append(("base64", rules)), encoded)[1],
    )

    adapters = create_default_adapters(None)
    assert isinstance(adapters["log_parse"], LogParseAdapter)
    session = {"raw_log_lines": ["kind=attack src=1"]}
    log_plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "log-export-tracer",
            "steps": [{"step_id": "log", "type": "log_parse"}],
        }
    )
    log_report = asyncio.run(
        PlanExecutor(adapters).execute(
            log_plan,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )
    from contracts.rule_source import RuleSourceFields

    source_fields = RuleSourceFields.create(product="产品", log_vendor="厂商")
    session["rule_source_fields"] = source_fields
    export_plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "rule-export-tracer",
            "steps": [
                {
                    "step_id": "export",
                    "type": "export",
                    "source_ref": "session.log_classification.sub_rules",
                }
            ],
        }
    )
    export_report = asyncio.run(
        PlanExecutor(adapters).execute(
            export_plan,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert log_report.status == StepStatus.SUCCESS
    assert export_report.status == StepStatus.SUCCESS
    assert [result.step_id for result in log_report.results] == ["log"]
    assert [result.step_id for result in export_report.results] == ["export"]
    assert session["log_classification"] == classification
    assert export_report.results[0].artifact.content == encoded
    assert export_report.results[0].artifact.download_kind == "unmappedconfig_subrules"
    assert calls[:3] == ["identify", "classify", "fill"]
    assert calls[3] == ("rules", classification, "sub", source_fields)
    assert calls[4] == ("base64", generated_rules)
