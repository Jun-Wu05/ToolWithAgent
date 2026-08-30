"""Issue #142: Prompt package ownership and compatibility gates."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest


PROMPT_LOADERS = {
    "load_enum_extract_prompt": "enum_extract.md",
    "load_enum_field_prompt": "enum_field.md",
    "load_event_classify_prompt": "event_classify.md",
    "load_field_strong_prompt": "field_strong.md",
    "load_field_weak_prompt": "field_weak.md",
    "load_kv_feature_identifier_prompt": "kv_feature_identifier.md",
    "load_log_classify_feature_prompt": "log_classify_feature.md",
    "load_log_feature_locate_prompt": "log_feature_locate.md",
    "load_log_format_identify_prompt": "log_format_identify.md",
    "load_log_header_classify_prompt": "log_header_classify.md",
    "load_planner_prompt": "planner.md",
    "load_threat_type_prompt": "threat_type.md",
}


def test_prompt_package_owns_planner_and_event_classify_loaders() -> None:
    """The final two Prompt resources must be loaded by the Prompt package."""
    import agent.prompts as prompts

    prompt_dir = Path(prompts.__file__).parent

    assert prompts.load_planner_prompt() == (prompt_dir / "planner.md").read_text(
        encoding="utf-8"
    )
    assert prompts.load_event_classify_prompt() == (
        prompt_dir / "event_classify.md"
    ).read_text(encoding="utf-8")


def test_all_prompt_assets_have_public_exact_loaders_and_exports() -> None:
    """Every current Prompt file has one public package loader."""
    import agent.prompts as prompts

    prompt_dir = Path(prompts.__file__).parent
    assert {path.name for path in prompt_dir.glob("*.md")} == set(
        PROMPT_LOADERS.values()
    )
    for loader_name, filename in PROMPT_LOADERS.items():
        assert loader_name in prompts.__all__
        assert getattr(prompts, loader_name)() == (prompt_dir / filename).read_text(
            encoding="utf-8"
        )
    assert "load_standard_fields" in prompts.__all__
    assert "get_prompts_dir" in prompts.__all__


def test_prompt_loaders_preserve_missing_policies(monkeypatch, tmp_path) -> None:
    """Optional, required, Planner and event loaders retain distinct failures."""
    import agent.prompts as prompts

    monkeypatch.setattr(prompts, "__file__", str(tmp_path / "__init__.py"))

    optional = {
        "load_log_format_identify_prompt",
        "load_log_classify_feature_prompt",
        "load_log_header_classify_prompt",
        "load_log_feature_locate_prompt",
        "load_kv_feature_identifier_prompt",
    }
    for loader_name in optional:
        assert getattr(prompts, loader_name)() == ""

    required = set(PROMPT_LOADERS) - optional - {
        "load_planner_prompt",
        "load_event_classify_prompt",
    }
    for loader_name in required:
        with pytest.raises(FileNotFoundError, match="提示词文件丢失"):
            getattr(prompts, loader_name)()

    with pytest.raises(FileNotFoundError) as planner_error:
        prompts.load_planner_prompt()
    assert "planner.md" in str(planner_error.value)

    with pytest.raises(FileNotFoundError, match="事件名称判定知识文件不存在"):
        prompts.load_event_classify_prompt()


def test_prompt_loaders_do_not_cache(monkeypatch, tmp_path) -> None:
    """A second load observes changed bytes, preserving the no-cache baseline."""
    import agent.prompts as prompts

    monkeypatch.setattr(prompts, "__file__", str(tmp_path / "__init__.py"))
    for loader_name, filename in PROMPT_LOADERS.items():
        prompt_path = tmp_path / filename
        prompt_path.write_text("first", encoding="utf-8")
        assert getattr(prompts, loader_name)() == "first"
        prompt_path.write_text("second", encoding="utf-8")
        assert getattr(prompts, loader_name)() == "second"


def test_prompt_consumers_use_the_package_and_legacy_exports_are_identical() -> None:
    """Consumers import canonical loaders; old log paths remain identity shims."""
    import agent.prompts as legacy_prompts
    import agent.prompts as prompts

    root = Path(__file__).parents[1]
    expected_imports = {
        root / "agent/core/planner.py": "load_planner_prompt",
        root / "agent/shared/event_classify.py": "load_event_classify_prompt",
    }
    for path, name in expected_imports.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == "agent.prompts"
            and any(alias.name == name for alias in node.names)
            for node in ast.walk(tree)
        )

    for name in legacy_prompts.__all__:
        assert getattr(legacy_prompts, name) is getattr(prompts, name)


def test_all_prompt_loaders_work_outside_repository_cwd() -> None:
    """Resource location depends on the package, never the working directory."""
    root = Path(__file__).parents[1]
    script = f"""
import json
import agent.prompts as prompts
names = {list(PROMPT_LOADERS)!r}
print(json.dumps([bool(getattr(prompts, name)()) for name in names]))
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
    assert json.loads(completed.stdout.strip()) == [True] * len(PROMPT_LOADERS)
