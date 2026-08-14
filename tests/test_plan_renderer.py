"""统一渲染器把执行产物落到界面的回归测试。"""

import asyncio
from types import SimpleNamespace


def test字段映射产物渲染为映射表且导出仍附下载(monkeypatch):
    """field_mapping 必须附 Dataframe 表格；config_export 仍附 File 下载（回归 #49）。"""
    import web.plan_renderer as renderer
    from web.planner_models import (
        ConfigExportArtifact,
        ExecutionReport,
        FieldMappingArtifact,
        FieldMappingRow,
        StepResult,
        StepStatus,
    )

    captured = {"dataframes": [], "files": [], "messages": []}

    class _FakeMessage:
        """记录发送时的文案与元素。"""

        def __init__(self, content, elements=None):
            self.content = content
            self.elements = elements or []

        async def send(self):
            captured["messages"].append(
                {"content": self.content, "elements": self.elements}
            )

    monkeypatch.setattr(renderer.cl, "Message", _FakeMessage)
    monkeypatch.setattr(
        renderer.cl,
        "Dataframe",
        lambda **kwargs: captured["dataframes"].append(kwargs) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        renderer.cl,
        "File",
        lambda **kwargs: captured["files"].append(kwargs) or SimpleNamespace(),
    )

    report = ExecutionReport(
        plan_id="plan-mix",
        results=(
            StepResult(
                step_id="fm-1",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=FieldMappingArtifact(
                    item_count=2,
                    mappings=(
                        FieldMappingRow(
                            original_field="src_ip",
                            standard_field="源IP",
                            match_status="匹配成功",
                        ),
                        FieldMappingRow(
                            original_field="foo",
                            standard_field="未匹配",
                            match_status="未匹配",
                        ),
                    ),
                    filled_config="filled-base64-config",
                ),
                message="步骤执行成功",
            ),
            StepResult(
                step_id="exp-1",
                operation_type="export",
                status=StepStatus.SUCCESS,
                artifact=ConfigExportArtifact(item_count=1, content="config-text"),
                message="步骤执行成功",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    # 步骤汇总文案仍包含步骤标识
    assert "fm-1" in captured["messages"][0]["content"]
    # 字段映射产物落表，含全部行（含未匹配）
    assert len(captured["dataframes"]) == 1
    table = captured["dataframes"][0]["data"]
    assert table.shape[0] == 2
    assert "src_ip" in set(table["原始字段名"])
    assert "未匹配" in set(table["匹配状态"])
    # 字段映射回填后附 mapped_config 下载，配置导出仍附 config 下载
    file_names = {f["name"] for f in captured["files"]}
    assert file_names == {"plan-mix_mapped_config.txt", "plan-mix_config.txt"}
    assert len(captured["messages"]) == 2
    download_message = captured["messages"][1]
    assert "已回填" in download_message["content"]
    assert "点击下载" in download_message["content"]
    assert "plan-mix_mapped_config.txt" in download_message["content"]
    assert len(download_message["elements"]) == 1


def test帮助决策渲染能力说明(monkeypatch):
    """guidance 决策渲染统一的能力说明消息，不进入执行渲染（回归 #42）。"""
    import web.plan_renderer as renderer
    from web.planner_models import PlanDecision

    sent = []

    class _Message:
        """记录发送文案，忽略元素。"""

        def __init__(self, content, elements=None):
            self.content = content

        async def send(self):
            sent.append(self.content)

    monkeypatch.setattr(renderer.cl, "Message", _Message)

    asyncio.run(
        renderer.render_decision(PlanDecision(decision="guidance", guidance_code="capabilities"))
    )

    assert len(sent) == 1
    assert "日志类型提取" in sent[0]
    assert "字段映射" in sent[0]


def _mount_chainlit_captures(monkeypatch, renderer):
    """挂载 Chainlit 消息/表格/文件捕获桩，返回 captured 字典。"""
    captured = {"dataframes": [], "files": [], "messages": []}

    class _Message:
        def __init__(self, *, content, elements):
            self.content = content
            self.elements = elements

        async def send(self):
            captured["messages"].append({"content": self.content, "elements": self.elements})

    monkeypatch.setattr(renderer.cl, "Message", _Message)
    monkeypatch.setattr(
        renderer.cl,
        "Dataframe",
        lambda **kwargs: captured["dataframes"].append(kwargs) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        renderer.cl,
        "File",
        lambda **kwargs: captured["files"].append(kwargs) or SimpleNamespace(),
    )
    return captured


def test威胁映射产物渲染为表格(monkeypatch):
    """威胁映射落表展示原始值、映射值和映射类型。"""
    import web.plan_renderer as renderer
    from web.planner_models import (
        ExecutionReport,
        StepResult,
        StepStatus,
        ThreatMappingArtifact,
        ThreatMappingRow,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-threat",
        results=(
            StepResult(
                step_id="threat-1",
                operation_type="threat_mapping",
                status=StepStatus.SUCCESS,
                artifact=ThreatMappingArtifact(
                    item_count=2,
                    mappings=(
                        ThreatMappingRow(mappingType="EQUAL", orgValue="attack", mappingValue="恶意活动"),
                        ThreatMappingRow(mappingType="EQUAL", orgValue="scan", mappingValue="扫描"),
                    ),
                ),
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["dataframes"]) == 1
    table = captured["dataframes"][0]["data"]
    assert set(table["原始值"]) == {"attack", "scan"}
    assert set(table["映射值"]) == {"恶意活动", "扫描"}
    assert set(table["类型"]) == {"EQUAL"}


def test枚举提取产物渲染为列表并附下载(monkeypatch):
    """枚举值落表展示并附文本下载。"""
    import web.plan_renderer as renderer
    from web.planner_models import EnumValuesArtifact, ExecutionReport, StepResult, StepStatus

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-enum",
        results=(
            StepResult(
                step_id="enum-1",
                operation_type="enum_extract",
                status=StepStatus.SUCCESS,
                artifact=EnumValuesArtifact(item_count=2, values=("attack", "scan")),
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["dataframes"]) == 1
    assert set(captured["dataframes"][0]["data"]["枚举值"]) == {"attack", "scan"}
    assert {item["name"] for item in captured["files"]} == {"plan-enum_enum_values.txt"}


def test日志类型提取产物渲染为类型表(monkeypatch):
    """日志分类产物落表展示日志类型、特征字段和样本数。"""
    import web.plan_renderer as renderer
    from web.planner_models import ExecutionReport, LogClassificationArtifact, StepResult, StepStatus

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-log",
        results=(
            StepResult(
                step_id="log-1",
                operation_type="log_parse",
                status=StepStatus.SUCCESS,
                artifact=LogClassificationArtifact(
                    item_count=2,
                    classification={
                        "攻击日志": {"feature": "attack", "samples": ["a", "b"]},
                        "审计日志": {"feature": "audit"},
                    },
                ),
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["dataframes"]) == 1
    table = captured["dataframes"][0]["data"]
    assert set(table["日志类型"]) == {"攻击日志", "审计日志"}


def test多产物复合计划渲染为单条汇总(monkeypatch):
    """复合计划的表格和配置下载进入同一条汇总消息。"""
    import web.plan_renderer as renderer
    from web.planner_models import (
        ConfigExportArtifact,
        EnumValuesArtifact,
        ExecutionReport,
        StepResult,
        StepStatus,
        ThreatMappingArtifact,
        ThreatMappingRow,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-compound",
        results=(
            StepResult(
                step_id="enum-1",
                operation_type="enum_extract",
                status=StepStatus.SUCCESS,
                artifact=EnumValuesArtifact(item_count=1, values=("attack",)),
            ),
            StepResult(
                step_id="threat-1",
                operation_type="threat_mapping",
                status=StepStatus.SUCCESS,
                artifact=ThreatMappingArtifact(
                    item_count=1,
                    mappings=(
                        ThreatMappingRow(mappingType="EQUAL", orgValue="attack", mappingValue="恶意活动"),
                    ),
                ),
            ),
            StepResult(
                step_id="fill-1",
                operation_type="fill",
                status=StepStatus.SUCCESS,
                changed_count=1,
                artifact=ConfigExportArtifact(item_count=1, content="config-text"),
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["messages"]) == 1
    assert len(captured["dataframes"]) == 2
    assert {item["name"] for item in captured["files"]} == {"plan-compound_config.txt", "plan-compound_enum_values.txt"}
