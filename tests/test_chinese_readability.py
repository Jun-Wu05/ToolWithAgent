"""统一 Planner 核心模块的中文可读性静态门禁。"""

import ast
import io
import tokenize
from pathlib import Path


CORE_MODULES = (
    Path("agent/core/planner.py"),
    Path("agent/shared/mapping_utils.py"),
    Path("contracts/planner_models.py"),
    Path("contracts/session_facts.py"),
    Path("web/plan_executor.py"),
    Path("contracts/progress.py"),
    Path("web/chainlit_progress.py"),
    Path("web/execution_adapters.py"),
    Path("web/plan_renderer.py"),
    Path("web/deterministic_plan.py"),
    Path("web/user_message_handlers.py"),
    Path("agent/core/team.py"),
    Path("web/action_callbacks.py"),
    Path("web/file_handlers.py"),
    Path("web/llm_client.py"),
    Path("web/session_state.py"),
    Path("web/utils.py"),
    Path("agent/prompts/__init__.py"),
    Path("web/chainlit_app.py"),
    Path("web/input_builder.py"),
    Path("contracts/__init__.py"),
    Path("web/adapters/__init__.py"),
    Path("web/adapters/shared.py"),
    Path("application/adapters/field_mapping.py"),
    Path("web/adapters/agent_ops.py"),
    Path("web/adapters/config_ops.py"),
    Path("web/execution_adapters.py"),
)


def _contains_chinese(text: str) -> bool:
    """判断文本是否包含中文字符；英文协议字段可与中文说明并存。"""
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def test核心模块类和函数均有中文docstring():
    """确保职责边界能够从代码内直接阅读，而不是依赖跨文件猜测。"""
    missing = []
    for path in CORE_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        module_docstring = ast.get_docstring(tree, clean=False) or ""
        if not _contains_chinese(module_docstring):
            missing.append(f"{path}:模块")
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node, clean=False) or ""
                if not _contains_chinese(docstring):
                    missing.append(f"{path}:{node.lineno}:{node.name}")
    assert not missing, "缺少中文 docstring：\n" + "\n".join(missing)


def test核心模块行内注释包含中文():
    """禁止新增纯英文注释，避免中文维护上下文被切碎。"""
    invalid = []
    for path in CORE_MODULES:
        source = path.read_text(encoding="utf-8-sig")
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            comment = token.string.lstrip("#").strip()
            if comment and not _contains_chinese(comment):
                invalid.append(f"{path}:{token.start[0]}:{comment}")
    assert not invalid, "存在纯英文注释：\n" + "\n".join(invalid)
