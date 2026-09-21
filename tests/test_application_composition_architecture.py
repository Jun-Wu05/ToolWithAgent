"""Issue #142: Application composition and dependency-direction gates."""

from __future__ import annotations

import ast
from pathlib import Path


EXPECTED_STEP_TYPES = {
    "log_parse",
    "log_knowledge_submit",
    "field_mapping",
    "enum_extract",
    "threat_mapping",
    "fill",
    "remove_mapping",
    "add_fields",
    "delete_fields",
    "merge_fields",
    "decode_fields",
    "regex_extract",
    "export",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots

def test_application_owns_the_default_adapter_composition() -> None:
    """The production Adapter factory belongs to Application."""
    from application.adapters.composition import create_default_adapters

    adapters = create_default_adapters(None)
    assert set(adapters) == EXPECTED_STEP_TYPES


def test_default_composition_uses_application_adapters_and_one_field_skill_instance() -> None:
    """The registry exposes every business Adapter through one Application seam."""
    from application.adapters.composition import create_default_adapters
    from application.adapters.enum_extract import EnumExtractAdapter
    from application.adapters.export import ExportAdapter
    from application.adapters.field_mapping import FieldMappingAdapter
    from application.adapters.field_skill import FIELD_SKILL_REGISTRY, FieldSkillAdapter
    from application.adapters.fill import FillAdapter
    from application.adapters.log_parse import LogParseAdapter
    from application.adapters.log_knowledge_submit import LogKnowledgeSubmitAdapter
    from application.adapters.remove_mapping import RemoveMappingAdapter
    from application.adapters.threat_mapping import ThreatMappingAdapter

    adapters = create_default_adapters(None)
    expected_types = {
        "log_parse": LogParseAdapter,
        "log_knowledge_submit": LogKnowledgeSubmitAdapter,
        "field_mapping": FieldMappingAdapter,
        "enum_extract": EnumExtractAdapter,
        "threat_mapping": ThreatMappingAdapter,
        "fill": FillAdapter,
        "remove_mapping": RemoveMappingAdapter,
        "export": ExportAdapter,
    }
    for step_type, adapter_type in expected_types.items():
        assert isinstance(adapters[step_type], adapter_type)

    skill_adapters = [adapters[name] for name in FIELD_SKILL_REGISTRY]
    assert all(isinstance(adapter, FieldSkillAdapter) for adapter in skill_adapters)
    assert len({id(adapter) for adapter in skill_adapters}) == 1


def test_only_one_factory_definition_and_migration_shims_are_deleted() -> None:
    """The completed migration leaves one production composition root."""
    from application.adapters import create_default_adapters as package_factory
    from application.adapters.composition import create_default_adapters

    assert package_factory is create_default_adapters

    root = Path(__file__).parents[1]
    assert not any((root / "web/adapters").glob("*.py"))
    assert not (root / "web/execution_adapters.py").exists()
    definitions = []
    for package in ("application", "web", "agent", "skills"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            definitions.extend(
                path.relative_to(root).as_posix()
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "create_default_adapters"
            )
    assert definitions == ["application/adapters/composition.py"]


def test_production_web_callers_import_application_composition_directly() -> None:
    """Web runtime delegates request execution through the Application runtime."""
    root = Path(__file__).parents[1]
    for relative in ("web/user_message_handlers.py", "web/deterministic_plan.py"):
        path = root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "application.request_runtime"
        ]
        assert len(imports) == 1


def test_package_dependency_direction_is_static_and_one_way() -> None:
    """Contracts are pure; Application, Agent and Skills never depend on UI."""
    root = Path(__file__).parents[1]
    rules = {
        "contracts": {"agent", "application", "skills", "web", "chainlit"},
        "application": {"web", "chainlit"},
        "agent": {"web", "chainlit"},
        "skills": {"web", "chainlit"},
    }
    violations = {}
    for package, forbidden in rules.items():
        for path in (root / package).rglob("*.py"):
            found = _imports(path) & forbidden
            if found:
                violations[path.relative_to(root).as_posix()] = sorted(found)
    assert violations == {}
