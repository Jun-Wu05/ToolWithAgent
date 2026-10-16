"""Issue #138：Application 威胁映射、填充与配置产物架构契约。"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
from pathlib import Path

from application.session_state import SessionState
from factories import make_session_state


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
                "mappingValue": "恶意程序", "ignored": "drop",
            }]}, ensure_ascii=False)

    member = Member()
    enum_artifact = EnumValuesArtifact(values=("攻击",), item_count=1, field="event_type")
    session = _recording_session(latest_enum_artifact=EnumArtifactSlot(
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


def _broken_enum_session():
    """构造枚举产物槽损坏的会话（#320 不可用分支共用夹具）。"""
    return make_session_state(latest_enum_artifact={"not": "a-valid-slot"})


def test威胁映射枚举产物不可用时执行器预检拦截() -> None:
    """槽损坏时 PlanExecutor 预检 needs_input artifact_source_unavailable（#320 补盲区）。"""
    from application.adapters import create_default_adapters
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_projection import build_session_facts
    from contracts.planner_models import PlanDecision, StepStatus, ThreatMappingStep

    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )
    session = _broken_enum_session()
    report = asyncio.run(
        PlanExecutor(create_default_adapters(None)).execute(
            PlanDecision(decision="execute", plan_id="enum-unavailable", steps=(step,)),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "artifact_source_unavailable"


def test威胁映射枚举产物不可用时适配器直连同码拦截() -> None:
    """直连 ThreatMappingAdapter 时同一前置语义生效（#320 补盲区）。"""
    from application.adapters import create_default_adapters
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import StepStatus, ThreatMappingStep

    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="session.artifacts.enum_values",
    )
    session = _broken_enum_session()
    result = asyncio.run(
        create_default_adapters(None)["threat_mapping"].execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.NEEDS_INPUT
    assert result.error_code == "artifact_source_unavailable"


def test威胁映射枚举前置两路径同码同文() -> None:
    """执行器预检与适配器直连对同一坏会话产出完全一致结果（#320 防漂移）。"""
    from application.adapters import create_default_adapters
    from application.execution import ExecutionContext, PlanExecutor
    from application.session_projection import build_session_facts
    from contracts.planner_models import PlanDecision, ThreatMappingStep

    def make_step() -> ThreatMappingStep:
        return ThreatMappingStep(
            step_id="threat", type="threat_mapping",
            source_ref="session.artifacts.enum_values",
        )

    executor_session = _broken_enum_session()
    executor_result = asyncio.run(
        PlanExecutor(create_default_adapters(None)).execute(
            PlanDecision(decision="execute", plan_id="drift-lock", steps=(make_step(),)),
            ExecutionContext(
                session=executor_session,
                session_facts=build_session_facts(executor_session),
            ),
        )
    ).results[0]
    adapter_session = _broken_enum_session()
    adapter_result = asyncio.run(
        create_default_adapters(None)["threat_mapping"].execute(
            make_step(),
            ExecutionContext(
                session=adapter_session,
                session_facts=build_session_facts(adapter_session),
            ),
            {},
        )
    )

    assert executor_result.error_code == adapter_result.error_code
    assert executor_result.message == adapter_result.message
    assert executor_result.message == "最近枚举值产物已不可用，请重新提取枚举值"


class _CoverageMember:
    """返回固定三列威胁映射的同步 ThreatAgent 替身（#277 失败关闭测试）。"""

    name = "ThreatAgent"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def run(self, model_input: str):
        self.calls.append(model_input)
        return self.response


class _RecordingSession(SessionState):
    """记录属性写入顺序的 Session 替身（垫片对 SessionState 走 setattr）。"""

    def __setattr__(self, name: str, value) -> None:
        if name != "writes" and hasattr(self, "writes"):
            self.writes.append(name)
        super().__setattr__(name, value)


def _recording_session(**overrides) -> _RecordingSession:
    """构造开始记录属性写入的会话替身（构造期字段初始化不入账）。"""
    session = _RecordingSession(**overrides)
    session.writes = []
    return session


def _run_threat_mapping(member, session, step) -> object:
    from application.adapters.threat_mapping import ThreatMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts

    return asyncio.run(ThreatMappingAdapter(
        type("Team", (), {"members": [member]})()
    ).execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {},
    ))


def test威胁映射来源外结果失败关闭不提交会话() -> None:
    """结构合法但来源外的结果必须拒绝，且不写入 Session 双槽（#277）。"""
    from contracts.planner_models import StepStatus, ThreatMappingStep
    from contracts.session_artifacts import ThreatArtifactSlot
    from contracts.planner_models import ThreatMappingArtifact, ThreatMappingRow

    member = _CoverageMember(json.dumps({"items": [
        {"mappingType": "EQUAL", "orgValue": "攻击", "mappingValue": "暴力破解"},
        {"mappingType": "EQUAL", "orgValue": "无关来源", "mappingValue": "端口扫描"},
    ]}, ensure_ascii=False))
    previous = ThreatArtifactSlot(
        artifact=ThreatMappingArtifact(
            mappings=(ThreatMappingRow.model_validate({
                "mappingType": "EQUAL", "orgValue": "old", "mappingValue": "暴力破解",
            }),),
            item_count=1,
            source_field="old_field",
        ),
        source_field="old_field",
    )
    session = _recording_session(latest_threat_artifact=previous)
    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="user.values", values=("攻击",),
    )

    result = _run_threat_mapping(member, session, step)

    assert result.status == StepStatus.FAILED
    assert result.error_code == "threat_mapping_coverage_rejected"
    assert len(member.calls) == 1
    assert session.writes == []
    assert session.latest_threat_artifact is previous


def test威胁映射缺项结果失败关闭不提交会话() -> None:
    """缺项结果不允许补「其他」兜底洗白为成功（#277）。"""
    from contracts.planner_models import StepStatus, ThreatMappingStep

    member = _CoverageMember(json.dumps({"items": [
        {"mappingType": "EQUAL", "orgValue": "攻击", "mappingValue": "暴力破解"},
    ]}, ensure_ascii=False))
    session = _recording_session()
    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="user.values", values=("攻击", "扫描"),
    )

    result = _run_threat_mapping(member, session, step)

    assert result.status == StepStatus.FAILED
    assert result.error_code == "threat_mapping_coverage_rejected"
    assert session.writes == []


def test威胁映射全数字代码输入needs_input且不调用模型() -> None:
    """无语义数字代码不允许模型猜测：先于调用返回稳定错误码（#277）。"""
    from contracts.planner_models import StepStatus, ThreatMappingStep

    member = _CoverageMember("[]")
    session = _recording_session()
    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="user.values", values=("30", "10"),
    )

    result = _run_threat_mapping(member, session, step)

    assert result.status == StepStatus.NEEDS_INPUT
    assert result.error_code == "threat_mapping_source_context_required"
    assert member.calls == []
    assert session.writes == []
    assert "语义" in result.message and "代码表" in result.message


def test威胁映射混合输入仍调用模型并按覆盖校验裁决() -> None:
    """混合输入不提前拒绝：照常调用并走统一覆盖校验（#277）。"""
    from contracts.planner_models import StepStatus, ThreatMappingStep

    member = _CoverageMember(json.dumps({"items": [
        {"mappingType": "REGULAR", "orgValue": "(?:30|攻击)", "mappingValue": "暴力破解"},
    ]}, ensure_ascii=False))
    session = _recording_session()
    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="user.values", values=("30", "攻击"),
    )

    result = _run_threat_mapping(member, session, step)

    assert result.status == StepStatus.SUCCESS
    assert len(member.calls) == 1
    assert session.writes == ["last_threat_data", "latest_threat_artifact"]


def test威胁映射依赖来源同样执行统一校验语义() -> None:
    """step:<id> 依赖来源的数字代码输入与直接值同码 needs_input（#277）。"""
    from application.adapters.threat_mapping import ThreatMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import (
        EnumValuesArtifact, StepResult, StepStatus, ThreatMappingStep,
    )

    member = _CoverageMember("[]")
    session = _recording_session()
    step = ThreatMappingStep(
        step_id="threat", type="threat_mapping",
        source_ref="step:enum-a", depends_on=("enum-a",),
    )
    dependency = StepResult(
        step_id="enum-a", operation_type="enum_extract",
        status=StepStatus.SUCCESS,
        artifact=EnumValuesArtifact(values=("30-10",), item_count=1, field="event_type"),
    )

    result = asyncio.run(ThreatMappingAdapter(
        type("Team", (), {"members": [member]})()
    ).execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {"enum-a": dependency},
    ))

    assert result.status == StepStatus.NEEDS_INPUT
    assert result.error_code == "threat_mapping_source_context_required"
    assert member.calls == []


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
    session = make_session_state(decoded_data=config, decoded_fields=["event_type"])
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
    assert decoded == json.dumps(session.decoded_data, ensure_ascii=False)
    assert decoded.startswith('[{"name": "规则一", "normalize":')
    assert '"mappingType": "REGULAR"' in decoded
    assert '"mappingValue": "恶意活动"' in decoded
    assert result.artifact.download_kind == "threatmapping_config"
