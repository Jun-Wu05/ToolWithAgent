"""五证据删除审计的版本化记录与自动扫描门禁（Issue #161）。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_module_usage import scan_module_usage


ROOT = Path(__file__).resolve().parents[1]
AUDIT_RECORD = (
    ROOT / "docs" / "architecture" / "audits" / "issue-161-five-evidence.json"
)


def _audit_payload() -> dict:
    return json.loads(AUDIT_RECORD.read_text(encoding="utf-8"))


def test_审计记录覆盖五个样本与五类证据() -> None:
    payload = _audit_payload()

    assert payload["schema_version"] == 1
    assert payload["issue"] == 161
    assert payload["scope"] == "audit-only"
    assert {item["id"] for item in payload["candidates"]} == {
        "base64-tool",
        "web-constants",
        "resilience",
        "confirmation-tool",
        "log-bridge-state",
    }

    required_evidence = {
        "production_imports",
        "dynamic_registrations",
        "package_reexports",
        "test_dependencies",
        "external_dependencies",
    }
    for candidate in payload["candidates"]:
        assert set(candidate["evidence"]) == required_evidence
        for module_path in candidate["module_paths"]:
            assert (ROOT / module_path).is_file(), "审计 Issue 不得删除候选模块"
        assert candidate["evidence"]["external_dependencies"]["status"] == (
            "pending-human-confirmation"
        )
        assert candidate["decision"] in {"retain-needs-info", "retain-active"}
        assert candidate["deletion_authorized"] is False


def test_仓库扫描结果与版本化内部证据一致() -> None:
    payload = _audit_payload()

    for candidate in payload["candidates"]:
        actual = scan_module_usage(
            ROOT,
            module_names=tuple(candidate["module_names"]),
            module_paths=tuple(candidate["module_paths"]),
        ).as_dict()
        for category in (
            "production_imports",
            "dynamic_registrations",
            "package_reexports",
            "test_dependencies",
        ):
            assert actual[category] == candidate["evidence"][category]


def test_扫描器识别延迟导入避免_log_pattern_store_假阴性() -> None:
    evidence = scan_module_usage(
        ROOT,
        module_names=("agent.tools.log_pattern_store",),
        module_paths=("agent/tools/log_pattern_store.py",),
    ).as_dict()

    imported_by = {item["path"] for item in evidence["production_imports"]}
    assert "agent/tools/pipeline/common/knowledge_store.py" in imported_by
    assert "agent/tools/pipeline/log_header_processor.py" in imported_by


def test_扫描器区分动态加载重导出与测试依赖() -> None:
    fixture_root = ROOT / "tests" / "fixtures" / "five_evidence_repo"

    evidence = scan_module_usage(
        fixture_root,
        module_names=("agent.tools.candidate",),
        module_paths=("agent/tools/candidate.py",),
    ).as_dict()

    assert {item["path"] for item in evidence["production_imports"]} == {
        "application/consumer.py"
    }
    assert {item["kind"] for item in evidence["dynamic_registrations"]} == {
        "decorator",
        "dynamic-import",
    }
    assert {item["path"] for item in evidence["package_reexports"]} == {
        "agent/tools/__init__.py"
    }
    assert {item["path"] for item in evidence["test_dependencies"]} == {
        "tests/candidate_dependency.py"
    }
