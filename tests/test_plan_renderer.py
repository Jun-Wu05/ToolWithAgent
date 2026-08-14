"""统一渲染器把执行产物落到界面的回归测试。"""

import asyncio
import io
import json
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
        renderer.cl, "Dataframe", lambda **kw: captured["dataframes"].append(kw) or SimpleNamespace()
    )
    monkeypatch.setattr(
        renderer.cl, "File", lambda **kw: captured["files"].append(kw) or SimpleNamespace()
    )
    return captured


def test威胁映射产物渲染为表格(monkeypatch):
    """threat_mapping 产物落表（原始值/映射值/类型），不只剩一行成功文案（回归 #31）。"""
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
                message="步骤执行成功",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["messages"]) == 1
    assert len(captured["dataframes"]) == 1
    table = captured["dataframes"][0]["data"]
    assert list(table.columns) == ["mappingType", "orgValue", "mappingValue"]
    assert set(table["orgValue"]) == {"attack", "scan"}
    assert set(table["mappingValue"]) == {"恶意活动", "扫描"}
    file_names = {f["name"] for f in captured["files"]}
    assert "plan-threat_threat_mapping.xlsx" in file_names
    assert "plan-threat_threat_mapping.txt" not in file_names
    threat_file = next(
        f for f in captured["files"] if f["name"] == "plan-threat_threat_mapping.xlsx"
    )
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(threat_file["content"]), read_only=True)
    worksheet = workbook.active
    rows = list(worksheet.values)
    assert rows[0] == ("mappingType", "orgValue", "mappingValue")
    assert rows[1] == ("EQUAL", "attack", "恶意活动")
    assert rows[2] == ("EQUAL", "scan", "扫描")


def test枚举提取产物渲染为列表并附下载(monkeypatch):
    """enum_values 产物落表并附可下载文件，保留旧的下载行为（回归 #24/#30）。"""
    import web.plan_renderer as renderer
    from web.planner_models import (
        EnumValuesArtifact,
        ExecutionReport,
        StepResult,
        StepStatus,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-enum",
        results=(
            StepResult(
                step_id="enum-1",
                operation_type="enum_extract",
                status=StepStatus.SUCCESS,
                artifact=EnumValuesArtifact(
                    item_count=2,
                    values=("attack", "scan"),
                    field="event_name",
                    regex=r'event_name="([^"]+)"',
                    original_log=("event_name=attack", "event_name=scan"),
                ),
                message="步骤执行成功",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["messages"]) == 1
    assert len(captured["dataframes"]) == 1
    assert set(captured["dataframes"][0]["data"]["枚举值"]) == {"attack", "scan"}
    file_names = {f["name"] for f in captured["files"]}
    assert "plan-enum_enum_values.json" in file_names
    assert "plan-enum_enum_values.txt" not in file_names
    enum_file = next(f for f in captured["files"] if f["name"] == "plan-enum_enum_values.json")
    enum_data = json.loads(enum_file["content"].decode("utf-8"))
    assert set(enum_data) == {"field", "regex", "original_log", "value"}
    assert enum_data["value"] == ["attack", "scan"]


def test日志类型提取产物渲染为类型表(monkeypatch):
    """log_classification 产物落表（日志类型/特征字段/样本数）（回归 log_parse 单意图展示）。"""
    import web.plan_renderer as renderer
    from web.planner_models import (
        ExecutionReport,
        LogClassificationArtifact,
        StepResult,
        StepStatus,
    )

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
                        "status": "SUCCESS",
                        "feature_field": "msg_type",
                        "classification_details": [
                            {
                                "logtype": "攻击日志",
                                "count": 2,
                                "matched_regex": "attack",
                                "coverage_pct": 66.7,
                                "real_samples": ["attack event=1", "attack event=2"],
                            },
                            {
                                "logtype": "审计日志",
                                "count": 1,
                                "matched_regex": "audit",
                                "coverage_pct": 33.3,
                                "real_samples": ["audit event=1"],
                            },
                        ],
                    },
                ),
                message="步骤执行成功",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["messages"]) == 1
    assert len(captured["dataframes"]) == 0
    content = captured["messages"][0]["content"]
    assert "### 📊 分类详情" in content
    assert "攻击日志" in content
    assert "attack event=1" in content
    assert "classification_details" not in content
    file_names = {f["name"] for f in captured["files"]}
    assert "plan-log_log_classification.json" in file_names
    assert "plan-log_log_classification.txt" not in file_names
    log_file = next(
        f for f in captured["files"] if f["name"] == "plan-log_log_classification.json"
    )
    log_data = json.loads(log_file["content"].decode("utf-8"))
    assert log_data["classification_details"][0]["logtype"] == "攻击日志"
    assert log_data["classification_details"][0]["real_samples"] == [
        "attack event=1",
        "attack event=2",
    ]


def test多产物复合计划渲染为单条汇总(monkeypatch):
    """复合计划多个产物类型全部进入同一条汇总消息的 elements（回归 #32）。"""
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
                message="步骤执行成功",
            ),
            StepResult(
                step_id="threat-1",
                operation_type="threat_mapping",
                status=StepStatus.SUCCESS,
                artifact=ThreatMappingArtifact(
                    item_count=1,
                    mappings=(ThreatMappingRow(mappingType="EQUAL", orgValue="attack", mappingValue="恶意活动"),),
                ),
                message="步骤执行成功",
            ),
            StepResult(
                step_id="fill-1",
                operation_type="fill",
                status=StepStatus.SUCCESS,
                changed_count=1,
                artifact=ConfigExportArtifact(item_count=1, content="config-text"),
                message="威胁映射已填充到目标字段",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    # 一条汇总消息，含两张表（枚举/威胁）+ 一个配置下载文件。
    assert len(captured["messages"]) == 1
    assert len(captured["dataframes"]) == 2
    file_names = {f["name"] for f in captured["files"]}
    assert "plan-compound_config.txt" in file_names
    assert "plan-compound_enum_values.json" in file_names
    assert "plan-compound_threat_mapping.xlsx" in file_names
