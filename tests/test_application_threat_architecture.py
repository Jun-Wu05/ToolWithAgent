"""Issue #138：Application 威胁映射、填充与配置产物架构契约。"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
from pathlib import Path


def _import_roots(path: Path) -> set[str]:
    """提取静态导入根，验证 Application 威胁模块不反向依赖 Web。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_application威胁模块不依赖web或chainlit() -> None:
    """威胁业务归 Application；Web 只拥有组合、展示和兼容导出。"""
    root = Path(__file__).parents[1]
    violations = {}
    for relative in (
        "application/adapters/threat_mapping.py",
        "application/adapters/threat_fill.py",
        "application/adapters/fill.py",
        "application/parsing.py",
    ):
        path = root / relative
        if not path.exists():
            violations[relative] = ["missing"]
            continue
        forbidden = _import_roots(path) & {"web", "chainlit"}
        if forbidden:
            violations[relative] = sorted(forbidden)
    assert violations == {}


def test默认组合直接使用application威胁适配器() -> None:
    """生产组合直接注册 Application 威胁适配器。"""
    from application.adapters.fill import FillAdapter
    from application.adapters.threat_mapping import ThreatMappingAdapter
    from application.adapters import create_default_adapters

    adapters = create_default_adapters(None)
    assert isinstance(adapters["threat_mapping"], ThreatMappingAdapter)
    assert isinstance(adapters["fill"], FillAdapter)


def test_web不再拥有威胁映射或填充实现() -> None:
    """兼容模块只委派或重导出，威胁实现不得跨接缝重新出现。"""
    root = Path(__file__).parents[1]
    assert not any((root / "web/adapters").glob("*.py"))
    assert not (root / "web/execution_adapters.py").exists()


def test威胁映射精确调用一次并按顺序提交双槽() -> None:
    """类型化适配器冻结精确模型输入、一次调用、血缘和 Session 提交顺序。"""
    from application.adapters.threat_mapping import ThreatMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import ThreatMappingStep, StepStatus
    from contracts.session_artifacts import EnumArtifactSlot
    from contracts.planner_models import EnumValuesArtifact

    class Member:
        name = "ThreatAgent"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, model_input: str):
            self.calls.append(model_input)
            return json.dumps({"items": [{
                "mappingType": "REGULAR", "orgValue": "攻击",
                "mappingValue": "恶意活动", "ignored": "drop",
            }]}, ensure_ascii=False)

    class Session(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.writes: list[str] = []

        def __setitem__(self, key, value):
            self.writes.append(key)
            super().__setitem__(key, value)

    member = Member()
    enum_artifact = EnumValuesArtifact(values=("攻击",), item_count=1, field="event_type")
    session = Session(latest_enum_artifact=EnumArtifactSlot(
        artifact=enum_artifact, source_field="event_type"
    ))
    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )
    result = asyncio.run(ThreatMappingAdapter(type("Team", (), {"members": [member]})()).execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {},
    ))

    assert result.status == StepStatus.SUCCESS
    assert member.calls == [json.dumps({"values": ["攻击"]}, ensure_ascii=False)]
    assert result.artifact.source_field == "event_type"
    assert result.artifact.mappings[0].mapping_type == "REGULAR"
    assert session.writes == ["last_threat_data", "latest_threat_artifact"]


def test威胁填充base64解码文本保持中文根结构键顺序与默认空格() -> None:
    """威胁配置产物继续使用既有 JSON 与 Base64 字节语义。"""
    from application.adapters.threat_fill import ThreatFillAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import (
        FillStep, StepResult, StepStatus, ThreatMappingArtifact, ThreatMappingRow,
    )

    config = [{"name": "规则一", "normalize": [{
        "index": "event_type", "field": "事件类型", "mappings": [],
    }]}]
    session = {"decoded_data": config, "decoded_fields": ["event_type"]}
    artifact = ThreatMappingArtifact(
        mappings=(ThreatMappingRow.model_validate({
            "mappingType": "REGULAR", "orgValue": "攻击", "mappingValue": "恶意活动",
        }),),
        item_count=1,
        source_field="event_type",
    )
    dependency = StepResult(
        step_id="threat", operation_type="threat_mapping",
        status=StepStatus.SUCCESS, artifact=artifact,
    )
    step = FillStep(
        step_id="fill", type="fill", fill_kind="threat",
        target_fields=("event_type",), source_ref="step:threat",
        config_ref="session.decoded_config", depends_on=("threat",),
    )
    result = asyncio.run(ThreatFillAdapter().execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {"threat": dependency},
    ))

    assert result.status == StepStatus.SUCCESS
    decoded = base64.b64decode(result.artifact.content).decode("utf-8")
    assert decoded == json.dumps(session["decoded_data"], ensure_ascii=False)
    assert decoded.startswith('[{"name": "规则一", "normalize":')
    assert '"mappingType": "REGULAR"' in decoded
    assert '"mappingValue": "恶意活动"' in decoded
    assert result.artifact.download_kind == "threatmapping_config"
