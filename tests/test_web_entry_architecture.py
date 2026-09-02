"""Issue #143: Chainlit registration and Application entry gates."""

from __future__ import annotations

import ast
from pathlib import Path


def _chainlit_decorators(path: Path) -> list[tuple[str, str | None]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Attribute) and isinstance(decorator.value, ast.Name):
                if decorator.value.id == "cl":
                    found.append((decorator.attr, None))
            elif (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "cl"
            ):
                value = None
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    value = str(decorator.args[0].value)
                found.append((decorator.func.attr, value))
    return found


def test_chainlit_lifecycle_hooks_are_registered_once() -> None:
    """Only the Chainlit composition root may register lifecycle hooks."""
    root = Path(__file__).parents[1]
    registrations = []
    for relative in (
        "web/chainlit_app.py",
        "web/start_handler.py",
        "web/settings_handler.py",
        "web/message_router.py",
    ):
        registrations.extend(_chainlit_decorators(root / relative))

    assert registrations.count(("on_chat_start", None)) == 1
    assert registrations.count(("on_settings_update", None)) == 1
    assert registrations.count(("on_message", None)) == 1


def test_web_entry_modules_do_not_own_agent_runtime_dependencies() -> None:
    """Chainlit entry modules reach model/cache runtime through Application."""
    root = Path(__file__).parents[1]
    forbidden = {
        "agent.core.team",
        "agent.core.model_config",
        "agent.core.field_retriever",
    }
    violations = []
    for relative in (
        "web/start_handler.py",
        "web/settings_handler.py",
        "web/message_router.py",
        "web/action_callbacks.py",
    ):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden:
                violations.append((relative, node.module, node.lineno))
    assert violations == []


def test_action_callbacks_are_registered_once() -> None:
    """Keep every user-visible Action callback registered exactly once."""
    root = Path(__file__).parents[1]
    expected = {
        "start_enum_fill",
        "export_rules",
        "export_sub_rules",
        "apply_field_mapping",
        "export_mapped_sub_rules",
        "submit_rule_source_fields",
        "cancel_rule_source_fields",
    }
    registrations = _chainlit_decorators(root / "web/action_callbacks.py")
    names = [value for decorator, value in registrations if decorator == "action_callback"]
    assert set(names) == expected
    assert len(names) == len(expected)
