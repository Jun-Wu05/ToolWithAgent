"""Issue #140：字段调整 Skills 链路的 Application 契约。"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path


def _import_roots(path: Path) -> set[str]:
    """读取静态导入根，阻止 Application 反向依赖界面层。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test字段skill适配器由application唯一实现并由生产组合直接注册() -> None:
    """Web 仅兼容重导出，五类步骤必须共用 Application 的同一适配器。"""
    root = Path(__file__).parents[1]
    module_path = root / "application/adapters/field_skill.py"
    assert module_path.exists()
    assert _import_roots(module_path).isdisjoint({"web", "chainlit"})

    from application.adapters.field_skill import (
        FIELD_SKILL_REGISTRY,
        FieldSkillAdapter,
    )
    from application.adapters import create_default_adapters
    from application.adapters.field_skill import FieldSkillAdapter as LegacyAdapter

    adapters = create_default_adapters(None)
    assert LegacyAdapter is FieldSkillAdapter
    assert set(FIELD_SKILL_REGISTRY) == {
        "add_fields",
        "delete_fields",
        "merge_fields",
        "decode_fields",
        "regex_extract",
    }
    assert {id(adapters[name]) for name in FIELD_SKILL_REGISTRY} == {
        id(adapters["add_fields"])
    }
    assert isinstance(adapters["add_fields"], FieldSkillAdapter)

    assert not any((root / "web/adapters").glob("*.py"))


def test字段skill注册表与application惰性导出保持精确契约() -> None:
    """脚本相对路径、函数名和公共包导出不能因迁移漂移。"""
    import application.adapters as adapters_package
    from application.adapters.field_skill import (
        FIELD_SKILL_REGISTRY,
        FieldSkillAdapter,
    )

    assert FIELD_SKILL_REGISTRY == {
        "add_fields": (r"skills\add-fields\scripts\add_fields.py", "add_field"),
        "delete_fields": (
            r"skills\delete-fields\scripts\delete_fields.py",
            "delete_field",
        ),
        "merge_fields": (
            r"skills\merge-fields\scripts\merge_fields.py",
            "merge_fields",
        ),
        "decode_fields": (
            r"skills\base64-decode-fields\scripts\decode_fields.py",
            "decode_fields",
        ),
        "regex_extract": (
            r"skills\regex-extract-field\scripts\extract_field.py",
            "extract_field",
        ),
    }
    assert "FieldSkillAdapter" in adapters_package.__all__
    assert "FIELD_SKILL_REGISTRY" in adapters_package.__all__
    assert adapters_package.FieldSkillAdapter is FieldSkillAdapter
    assert adapters_package.FIELD_SKILL_REGISTRY is FIELD_SKILL_REGISTRY


def test字段skill脚本从非仓库cwd与冷启动顺序均可定位(tmp_path: Path) -> None:
    """资源定位基于包位置，先导入旧入口也不能形成初始化环。"""
    root = Path(__file__).parents[1]
    script = """
import json
import application.adapters.field_skill as legacy
from application.adapters import FIELD_SKILL_REGISTRY, FieldSkillAdapter
from application.adapters.field_skill import _load_skill_function

loaded = {
    step_type: _load_skill_function(step_type).__name__
    for step_type in FIELD_SKILL_REGISTRY
}
print(json.dumps({
    "identity": legacy.FieldSkillAdapter is FieldSkillAdapter,
    "loaded": loaded,
}, ensure_ascii=False))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.splitlines()[-1]) == {
        "identity": True,
        "loaded": {
            "add_fields": "add_field",
            "delete_fields": "delete_field",
            "merge_fields": "merge_fields",
            "decode_fields": "decode_fields",
            "regex_extract": "extract_field",
        },
    }
