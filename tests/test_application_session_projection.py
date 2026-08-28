"""Issue #132: Contracts types and Application session projection seams."""

from __future__ import annotations

import ast
from pathlib import Path

from contracts.planner_models import EnumValuesArtifact
from contracts.session_artifacts import EnumArtifactSlot


def test_contracts_do_not_import_runtime_or_domain_packages() -> None:
    """Contracts must remain pure types with no implementation reverse dependency."""
    forbidden_roots = {"agent", "application", "chainlit", "web"}
    violations: list[str] = []
    contracts_dir = Path(__file__).parents[1] / "contracts"

    for path in sorted(contracts_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_roots: set[str] = set()
            if isinstance(node, ast.Import):
                imported_roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots = {node.module.split(".", 1)[0]}
            for root in sorted(imported_roots & forbidden_roots):
                violations.append(f"{path.name}:{node.lineno} imports {root}")

    assert violations == []


def test_application_projects_stable_safe_session_facts() -> None:
    """Application owns reads, target binding, annotations and artifact redaction."""
    from application.session_projection import build_session_facts

    session = {
        "api_key": "secret-key",
        "enum_excel_path": r"C:\private\mapping.xlsx",
        "decoded_data": {
            "name": "decoded-rule",
            "normalize": [{"index": "alarm_name", "field": "event_name"}],
        },
        "decoded_fields": ["original_log", "alarm_name"],
        "enum_preview": [{"目标字段": "event_name", "原始值": "raw-secret"}],
        "mapped_sub_rules": [
            {
                "name": "AUDIT_kv_子规则",
                "normalize": [{"index": "src_ip", "field": "源IP"}],
                "parser": {
                    "filter": [
                        {"name": "addFields", "id": "", "fields": {"事件名称": "审计事件"}}
                    ]
                },
            }
        ],
        "latest_enum_artifact": EnumArtifactSlot(
            artifact=EnumValuesArtifact(
                values=("artifact-secret",), item_count=1, field="alarm_name"
            ),
            source_field="alarm_name",
        ),
    }

    facts = build_session_facts(session)

    assert facts.available_config_refs == (
        "session.decoded_config",
        "session.mapped_sub_rules",
    )
    assert facts.available_fields == ("alarm_name", "src_ip", "源IP")
    assert facts.enum_mapping_target_fields == ("event_name",)
    assert facts.decoded_config_rule_names == ("decoded-rule",)
    assert facts.mapped_sub_rule_names == ("AUDIT_kv_子规则", "addFields")
    assert facts.event_annotations[0].event_name == "审计事件"
    assert facts.event_annotations[0].event_level == "信息"
    assert facts.referenceable_artifacts[0].source_ref == "session.artifacts.enum_values"
    assert facts.referenceable_artifacts[0].target_bindings[0].target_field == "event_name"

    dumped = facts.model_dump_json()
    for sensitive_value in (
        "secret-key",
        "private",
        "raw-secret",
        "artifact-secret",
    ):
        assert sensitive_value not in dumped
