"""Issue #137：Application 枚举链路、附件生命周期与字节契约。"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
from pathlib import Path


def _import_roots(path: Path) -> set[str]:
    """提取静态导入根，验证 Application 枚举模块不反向依赖 Web。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_application枚举模块不依赖web或chainlit() -> None:
    """枚举业务归 Application；Web 只拥有上传交互和兼容导出。"""
    root = Path(__file__).parents[1]
    violations = {}
    for relative in (
        "application/adapters/enum_extract.py",
        "application/adapters/enum_fill.py",
        "application/adapters/fill_shared.py",
        "application/enum_mapping_attachments.py",
    ):
        path = root / relative
        if not path.exists():
            violations[relative] = ["missing"]
            continue
        forbidden = _import_roots(path) & {"web", "chainlit"}
        if forbidden:
            violations[relative] = sorted(forbidden)
    assert violations == {}


def test默认组合直接使用application枚举适配器() -> None:
    """生产组合直接注册 Application 枚举适配器。"""
    from application.adapters.enum_extract import EnumExtractAdapter
    from application.adapters import create_default_adapters

    adapters = create_default_adapters(None)
    assert isinstance(adapters["enum_extract"], EnumExtractAdapter)
    assert "fill" in adapters


def test_web不再拥有枚举提取或填充实现() -> None:
    """兼容模块只委派或重导出，枚举实现不得跨接缝重新出现。"""
    root = Path(__file__).parents[1]
    assert not any((root / "web/adapters").glob("*.py"))
    assert not (root / "web/execution_adapters.py").exists()


def test枚举prompt内容和缺失策略不变(monkeypatch) -> None:
    """枚举 Prompt 经包位置加载，内容逐字一致且缺失时继续立即失败。"""
    import agent.prompts as prompts

    prompt_dir = Path(prompts.__file__).parent
    assert prompts.load_enum_extract_prompt() == (prompt_dir / "enum_extract.md").read_text(
        encoding="utf-8"
    )
    monkeypatch.setattr(prompts, "__file__", str(prompt_dir / "missing" / "__init__.py"))
    try:
        prompts.load_enum_extract_prompt()
    except FileNotFoundError as error:
        assert "enum_extract.md" in str(error)
    else:
        raise AssertionError("枚举 Prompt 缺失时应保持立即失败策略")


def test枚举提取prompt和模型各调用一次且参数与提交顺序冻结() -> None:
    """公开适配器接口冻结 Prompt、直连模型参数、字段顺序和双槽提交。"""
    from application.adapters.enum_extract import EnumExtractAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import EnumExtractStep, StepStatus

    calls: list[tuple] = []

    def load_prompt() -> str:
        calls.append(("prompt",))
        return "ENUM PROMPT"

    def call_model(model_input: str, **kwargs):
        calls.append(("model", model_input, kwargs))
        return json.dumps({"field": "event_type", "regex": r"event_type=(\w+)"})

    class RecordingSession(dict):
        """记录成功后的兼容 Session 写入顺序。"""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.writes: list[str] = []

        def __setitem__(self, key, value):
            self.writes.append(key)
            super().__setitem__(key, value)

    session = RecordingSession(
        raw_log_lines=["event_type=attack", "event_type=scan"],
        decoded_fields=["event_type"],
    )
    result = asyncio.run(
        EnumExtractAdapter(llm_caller=call_model, prompt_loader=load_prompt).execute(
            EnumExtractStep(
                step_id="enum", type="enum_extract", target_field="event_type",
                source_ref="session.logs",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.values == ("attack", "scan")
    assert [call[0] for call in calls] == ["prompt", "model"]
    assert calls[1][2] == {"temperature": 0.1, "max_tokens": 500, "timeout": 120}
    assert calls[1][1].startswith("ENUM PROMPT\n\n目标字段：event_type")
    assert session.writes == ["last_enum_extract_result", "latest_enum_artifact"]


def test枚举附件在application中累积同名替换并标记待重填() -> None:
    """附件提交模块隐藏 Sheet 身份、过期配置和待重填集合的状态转换。"""
    from application.enum_mapping_attachments import commit_enum_mapping_attachment

    session = {
        "enum_mapping_sheets": {
            "severity": [{"mappingType": "EQUAL", "orgValue": "high", "mappingValue": "高"}]
        },
        "enum_fill_contributions": {
            "session.decoded_config": {"severity": [{"mapping": {"orgValue": "high"}}]}
        },
    }
    preview = commit_enum_mapping_attachment(
        session,
        "new.xlsx",
        {
            "action": [{"mappingType": "EQUAL", "orgValue": "allow", "mappingValue": "允许"}],
            "severity": [{"mappingType": "EQUAL", "orgValue": "critical", "mappingValue": "严重"}],
        },
    )

    assert set(session["enum_mapping_sheets"]) == {"severity", "action"}
    assert session["enum_mapping_sheets"]["severity"][0]["orgValue"] == "critical"
    assert [row["目标字段"] for row in preview] == ["severity", "action"]
    assert session["stale_enum_config_refs"] == {"session.decoded_config"}
    assert session["enum_pending_refills"] == {
        "session.decoded_config": {"severity", "action"}
    }


def test枚举填充base64解码文本保持中文根结构键顺序与默认空格() -> None:
    """枚举配置产物继续使用该业务自己的 JSON 与 Base64 字节语义。"""
    from application.adapters.enum_fill import EnumFillAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import FillStep, StepStatus

    config = {
        "name": "规则一",
        "normalize": [{"index": "severity", "field": "严重级别", "mappings": []}],
    }
    session = {
        "decoded_data": config,
        "decoded_fields": ["severity"],
        "enum_preview": [{
            "目标字段": "severity", "mappingType": "EQUAL",
            "orgValue": "high", "mappingValue": "高",
        }],
    }
    step = FillStep(
        step_id="fill", type="fill", fill_kind="enum",
        target_fields=("severity",), source_ref="session.enum_mapping_table",
        config_ref="session.decoded_config",
    )
    result = asyncio.run(
        EnumFillAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    decoded = base64.b64decode(result.artifact.content).decode("utf-8")
    assert decoded == json.dumps(session["decoded_data"], ensure_ascii=False)
    assert decoded.startswith('{"name": "规则一", "normalize":')
    assert '"mappingValue": "高"' in decoded
