"""扫描删除候选的四类仓库内使用证据。

该工具只收集证据，不推导删除权限。仓库外依赖必须另行人工确认。
"""

from __future__ import annotations

import argparse
import ast
import json
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


_PRODUCTION_ROOTS = {"agent", "application", "contracts", "skills", "web"}
_IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "agno_repo",
    "archive",
    "outputs",
    "tmp",
}
_DYNAMIC_IMPORT_CALLS = {
    "import_module",
    "importlib.import_module",
    "spec_from_file_location",
    "importlib.util.spec_from_file_location",
}


@dataclass(frozen=True, order=True)
class EvidenceLocation:
    """一条可回到源码复核的仓库内证据。"""

    path: str
    line: int
    kind: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RepositoryEvidence:
    """删除审计中可由当前仓库自动证明的四类证据。"""

    production_imports: tuple[EvidenceLocation, ...]
    dynamic_registrations: tuple[EvidenceLocation, ...]
    package_reexports: tuple[EvidenceLocation, ...]
    test_dependencies: tuple[EvidenceLocation, ...]

    def as_dict(self) -> dict[str, list[dict[str, object]]]:
        return {
            "production_imports": [item.as_dict() for item in self.production_imports],
            "dynamic_registrations": [
                item.as_dict() for item in self.dynamic_registrations
            ],
            "package_reexports": [item.as_dict() for item in self.package_reexports],
            "test_dependencies": [item.as_dict() for item in self.test_dependencies],
        }


def _python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in _IGNORED_PARTS for part in relative.parts):
            continue
        if relative.parts and (
            relative.parts[0] in _PRODUCTION_ROOTS or relative.parts[0] == "tests"
        ):
            yield path


@lru_cache(maxsize=None)
def _parsed_python_files(root_text: str) -> tuple[tuple[Path, ast.AST], ...]:
    """单次测试进程内复用 AST，避免每个候选重复解析整个仓库。"""

    root = Path(root_text)
    parsed: list[tuple[Path, ast.AST]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parsed.append((path, tree))
    return tuple(parsed)


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _module_for_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return ".".join(parts)


def _resolved_from_module(root: Path, path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = _module_for_path(root, path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    keep = max(0, len(package) - node.level + 1)
    prefix = package[:keep]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _import_matches(module: str, aliases: Iterable[ast.alias], targets: set[str]) -> bool:
    if any(module == target or module.startswith(f"{target}.") for target in targets):
        return True
    imported = {f"{module}.{alias.name}".strip(".") for alias in aliases}
    return bool(imported & targets)


def _string_arguments(node: ast.Call) -> tuple[str, ...]:
    values: list[str] = []
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            values.append(arg.value.replace("\\", "/"))
    return tuple(values)


def _dynamic_call_matches(
    node: ast.Call, module_names: set[str], module_paths: set[str]
) -> bool:
    call_name = _dotted_name(node.func)
    if call_name not in _DYNAMIC_IMPORT_CALLS:
        return False
    for value in _string_arguments(node):
        if value in module_names:
            return True
        if any(value.endswith(path) for path in module_paths):
            return True
    return False


def _decorator_findings(
    root: Path,
    target_paths: set[str],
    parsed_files: tuple[tuple[Path, ast.AST], ...],
) -> list[EvidenceLocation]:
    findings: list[EvidenceLocation] = []
    for path, tree in parsed_files:
        relative_path = path.relative_to(root).as_posix()
        if relative_path not in target_paths:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for decorator in node.decorator_list:
                expression = decorator.func if isinstance(decorator, ast.Call) else decorator
                name = _dotted_name(expression)
                if name == "tool" or name.endswith(".tool"):
                    findings.append(
                        EvidenceLocation(
                            path=relative_path,
                            line=decorator.lineno,
                            kind="decorator",
                            detail=f"@{name}",
                        )
                    )
    return findings


def scan_module_usage(
    root: Path,
    *,
    module_names: tuple[str, ...],
    module_paths: tuple[str, ...],
) -> RepositoryEvidence:
    """扫描一个或多个共同审计对象的仓库内使用证据。

    函数体内的 import 仍属于生产导入，因此扫描完整 AST；包 ``__init__.py``
    的导入单列为重导出。动态 import 和定义模块上的 ``@tool`` 单列为动态
    注册/加载证据。
    """

    root = root.resolve()
    targets = set(module_names)
    target_paths = {path.replace("\\", "/") for path in module_paths}
    missing_paths = sorted(path for path in target_paths if not (root / path).is_file())
    if missing_paths:
        raise FileNotFoundError(
            "审计目标不存在；审计记录不能替代独立删除授权："
            + ", ".join(missing_paths)
        )
    parsed_files = _parsed_python_files(str(root))
    production: list[EvidenceLocation] = []
    dynamic = _decorator_findings(root, target_paths, parsed_files)
    reexports: list[EvidenceLocation] = []
    tests: list[EvidenceLocation] = []

    for path, tree in parsed_files:
        relative = path.relative_to(root).as_posix()
        is_test = relative.startswith("tests/")
        is_reexport = path.name == "__init__.py" and not is_test
        is_target = relative in target_paths

        for node in ast.walk(tree):
            matched_import = False
            detail = ""
            if isinstance(node, ast.Import):
                matched = [alias.name for alias in node.names if alias.name in targets]
                matched_import = bool(matched)
                detail = ", ".join(matched)
            elif isinstance(node, ast.ImportFrom):
                module = _resolved_from_module(root, path, node)
                matched_import = _import_matches(module, node.names, targets)
                detail = module

            if matched_import and not is_target:
                finding = EvidenceLocation(
                    path=relative,
                    line=node.lineno,
                    kind="import",
                    detail=detail,
                )
                if is_test:
                    tests.append(finding)
                elif is_reexport:
                    reexports.append(finding)
                elif relative.split("/", 1)[0] in _PRODUCTION_ROOTS:
                    production.append(finding)

            if (
                isinstance(node, ast.Call)
                and not is_target
                and _dynamic_call_matches(node, targets, target_paths)
            ):
                dynamic.append(
                    EvidenceLocation(
                        path=relative,
                        line=node.lineno,
                        kind="dynamic-import",
                        detail=_dotted_name(node.func),
                    )
                )

    return RepositoryEvidence(
        production_imports=tuple(sorted(set(production))),
        dynamic_registrations=tuple(sorted(set(dynamic))),
        package_reexports=tuple(sorted(set(reexports))),
        test_dependencies=tuple(sorted(set(tests))),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--module", action="append", required=True)
    parser.add_argument("--path", action="append", required=True)
    args = parser.parse_args()
    evidence = scan_module_usage(
        args.root,
        module_names=tuple(args.module),
        module_paths=tuple(args.path),
    )
    print(json.dumps(evidence.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
