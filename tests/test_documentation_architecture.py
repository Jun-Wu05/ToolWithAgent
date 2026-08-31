"""现行架构文档与最终 Application 运行时的一致性门禁。"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAINTAINED_ARCHITECTURE_DOCS = (
    ROOT / "README.md",
    ROOT / "CONTEXT.md",
    ROOT / "docs" / "architecture" / "架构概览.md",
    ROOT / "docs" / "architecture" / "领域能力目录.md",
    ROOT / "docs" / "architecture" / "代码级设计说明.md",
    ROOT / "docs" / "architecture" / "chainlit_app模块说明.md",
    ROOT / "docs" / "architecture" / "统一Planner架构.md",
    ROOT / "docs" / "architecture" / "测试场景手册.md",
)


def _maintained_architecture_text() -> str:
    """合并当前事实源文档，避免把历史 ADR 当成待改写对象。"""

    return "\n".join(path.read_text(encoding="utf-8") for path in MAINTAINED_ARCHITECTURE_DOCS)


def test_现行文档只把最终application模块描述为生产运行时() -> None:
    text = _maintained_architecture_text()

    removed_runtime_paths = (
        "web/plan_executor.py",
        "web/session_state.py",
        "web/history_store.py",
        "web/execution_adapters.py",
        "web/adapters/",
        "agent/core/prompts.py",
    )
    for path in removed_runtime_paths:
        assert path not in text, f"现行文档仍把已删除路径描述为当前实现：{path}"

    current_runtime_paths = (
        "application/request_runtime.py",
        "application/execution.py",
        "application/session_state.py",
        "application/history.py",
        "application/model_runtime.py",
        "application/field_runtime.py",
        "application/file_input.py",
        "application/adapters/",
    )
    for path in current_runtime_paths:
        assert path in text, f"现行文档缺少最终 Application 入口：{path}"


def _production_python_files() -> tuple[Path, ...]:
    patterns = (
        "application/**/*.py",
        "contracts/**/*.py",
        "web/**/*.py",
        "agent/**/*.py",
        "skills/**/scripts/**/*.py",
    )
    paths = {path for pattern in patterns for path in ROOT.glob(pattern)}
    return tuple(sorted(paths))


def _source_analysis_payload() -> tuple[str, dict]:
    html = (ROOT / "docs" / "source-code-analysis.html").read_text(encoding="utf-8")
    match = re.search(
        r'<script id="source-analysis-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    assert match, "源码分析页缺少可验证的 source-analysis-data 快照"
    return html, json.loads(match.group(1))


def test_源码分析快照与最终生产文件和物理行数一致() -> None:
    html, payload = _source_analysis_payload()
    expected = {
        path.relative_to(ROOT).as_posix(): len(path.read_text(encoding="utf-8").splitlines())
        for path in _production_python_files()
    }
    actual = {item["path"]: item["lines"] for item in payload["files"]}

    assert actual == expected
    assert payload["totals"] == {"files": len(expected), "lines": sum(expected.values())}
    assert "Application 运行时" in {item["layer"] for item in payload["files"]}

    removed_paths = (
        "web/plan_executor.py",
        "web/session_state.py",
        "web/history_store.py",
        "web/execution_adapters.py",
    )
    assert all(path not in actual for path in removed_paths)

    for item in payload["files"]:
        for relation in (*item["imports"], *item["callers"]):
            assert (ROOT / relation).is_file(), f"源码分析关系指向不存在文件：{relation}"

    assert str(ROOT).casefold() not in html.casefold()
    assert not re.search(r"(?:sk|ghp|github_pat)-?[A-Za-z0-9_]{20,}", html)


def test_现行文档内部链接和历史边界可验证() -> None:
    current_docs = (
        *MAINTAINED_ARCHITECTURE_DOCS,
        ROOT / "docs" / "adr" / "0009-application-runtime-ownership.md",
        ROOT / "CHANGELOG.md",
    )
    broken_links = []
    for document in current_docs:
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", text):
            clean_target = target.split("#", 1)[0].strip()
            if not clean_target or re.match(r"^[a-z]+://", clean_target):
                continue
            resolved = (document.parent / clean_target).resolve()
            if not resolved.exists():
                broken_links.append((document.relative_to(ROOT).as_posix(), target))
    assert broken_links == []

    adr = (ROOT / "docs" / "adr" / "0009-application-runtime-ownership.md").read_text(
        encoding="utf-8"
    )
    assert "ADR-0001～ADR-0004" in adr
    assert "属于当时历史" in adr
    assert "docs/adr/0009-application-runtime-ownership.md" in (ROOT / "README.md").read_text(
        encoding="utf-8"
    )
