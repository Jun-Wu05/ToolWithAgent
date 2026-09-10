"""统一渲染器把执行产物落到界面的回归测试。"""

import asyncio
import io
import json
from datetime import datetime
from types import SimpleNamespace


def test字段映射产物渲染为映射表且导出仍附下载(monkeypatch):
    """field_mapping 必须附 Dataframe 表格；config_export 仍附 File 下载（回归 #49）。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
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

        def __init__(self, content, elements=None, actions=None):
            self.content = content
            self.elements = elements or []
            self.actions = actions or []

        async def send(self):
            captured["messages"].append(
                {
                    "content": self.content,
                    "elements": self.elements,
                    "actions": self.actions,
                }
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
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
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
                    download_kind="mapped_config",
                    download_content="filled-base64-config",
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
    assert file_names == {
        "fieldmapped_config_20260818_1006.txt",
        "current_config_20260818_1006.txt",
    }
    assert len(captured["messages"]) == 4
    assert captured["messages"][0]["elements"] == []
    assert len(captured["messages"][1]["elements"]) == 1
    assert len(captured["messages"][2]["elements"]) == 1
    download_message = captured["messages"][3]
    assert "已回填" in download_message["content"]
    assert "点击下载" in download_message["content"]
    assert "fieldmapped_config_20260818_1006.txt" in download_message["content"]
    assert len(download_message["elements"]) == 1
    assert [action.name for action in captured["messages"][0]["actions"]] == [
        "export_mapped_sub_rules",
    ]


def test日志分类结果恢复规则生成与字段映射动作(monkeypatch):
    """日志分类结果必须提供规则生成和标准字段映射入口。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import ExecutionReport, LogClassificationArtifact, StepResult, StepStatus

    captured = {"messages": []}

    class _Message:
        """记录消息及其动作。"""

        def __init__(self, *, content, elements=None, actions=None):
            self.content = content
            self.elements = elements or []
            self.actions = actions or []

        async def send(self):
            captured["messages"].append(self)

    monkeypatch.setattr(renderer.cl, "Message", _Message)
    monkeypatch.setattr(renderer.cl, "File", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(renderer, "create_dataframe_elements", lambda rows: [])

    report = ExecutionReport(
        plan_id="plan-log",
        results=(
            StepResult(
                step_id="log-1",
                operation_type="log_parse",
                status=StepStatus.SUCCESS,
                artifact=LogClassificationArtifact(
                    item_count=1,
                    classification={"AUDIT": {"feature": "log_type"}},
                ),
                message="步骤执行成功",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["messages"]) == 2
    assert captured["messages"][0].elements == []
    assert len(captured["messages"][1].elements) == 1
    assert [action.name for action in captured["messages"][0].actions] == [
        "apply_field_mapping",
        "export_rules",
        "export_sub_rules",
    ]


def test帮助决策渲染能力说明(monkeypatch):
    """guidance 决策渲染统一的能力说明消息，不进入执行渲染（回归 #42）。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import PlanDecision

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


def test提案只渲染只读步骤和确认选项(monkeypatch):
    import web.plan_renderer as renderer
    from contracts.planner_models import PlanDecision

    sent = []

    class _Message:
        def __init__(self, content, elements=None):
            self.content = content
            self.elements = elements or []

        async def send(self):
            sent.append((self.content, self.elements))

    monkeypatch.setattr(renderer.cl, "Message", _Message)
    proposal = PlanDecision.model_validate(
        {
            "decision": "proposal",
            "plan_id": "proposal-log",
            "reason_code": "confirmation_required",
            "question": "将识别日志类型，是否执行？",
            "choices": ["确认执行", "取消"],
            "steps": [{"step_id": "log-1", "type": "log_parse"}],
        }
    )

    asyncio.run(renderer.render_decision(proposal))

    assert len(sent) == 1
    assert "计划步骤" in sent[0][0]
    assert "`log_parse`" in sent[0][0]
    assert "确认执行" in sent[0][0]
    assert sent[0][1] == []


def _mount_chainlit_captures(monkeypatch, renderer):
    """挂载 Chainlit 消息/表格/文件捕获桩，返回 captured 字典。"""
    captured = {"dataframes": [], "files": [], "messages": []}

    class _Message:
        def __init__(self, *, content, elements, actions=None):
            self.content = content
            self.elements = elements
            self.actions = actions or []

        async def send(self):
            captured["messages"].append(
                {
                    "content": self.content,
                    "elements": self.elements,
                    "actions": self.actions,
                }
            )

    monkeypatch.setattr(renderer.cl, "Message", _Message)
    monkeypatch.setattr(
        renderer.cl,
        "Dataframe",
        lambda **kw: captured["dataframes"].append(kw)
        or SimpleNamespace(element_type="dataframe", **kw),
    )
    monkeypatch.setattr(
        renderer.cl,
        "File",
        lambda **kw: captured["files"].append(kw)
        or SimpleNamespace(element_type="file", **kw),
    )
    return captured


def test配置产物按七种业务语义生成下载名且内容不变(monkeypatch):
    """配置下载名由显式产物语义决定，不再使用 plan_id 或步骤文案猜测。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import ConfigExportArtifact, ExecutionReport, StepResult, StepStatus

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
    )
    cases = (
        ("enummapping_config", "enummapping_config_20260818_1006.txt"),
        ("threatmapping_config", "threatmapping_config_20260818_1006.txt"),
        ("cancelmapping_config", "cancelmapping_config_20260818_1006.txt"),
        ("current_config", "current_config_20260818_1006.txt"),
        ("mappedconfig_subrules", "mappedconfig_subrules_20260818_1006.txt"),
        ("mappedconfig_mainrules", "mappedconfig_mainrules_20260818_1006.txt"),
        ("unmappedconfig_subrules", "unmappedconfig_subrules_20260818_1006.txt"),
    )
    report = ExecutionReport(
        plan_id="semantic-downloads",
        results=tuple(
            StepResult(
                step_id=f"export-{index}",
                operation_type="export",
                status=StepStatus.SUCCESS,
                artifact=ConfigExportArtifact(
                    item_count=1,
                    content=f"content-{index}",
                    download_kind=kind,
                ),
                message="配置已导出",
            )
            for index, (kind, _expected_name) in enumerate(cases)
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    files_by_name = {item["name"]: item["content"] for item in captured["files"]}
    assert set(files_by_name) == {expected_name for _kind, expected_name in cases}
    for index, (_kind, expected_name) in enumerate(cases):
        assert files_by_name[expected_name] == f"content-{index}".encode("utf-8")


def test字段映射后的解析子规则使用明确文件名和说明(monkeypatch):
    """mapped_sub_rules 下载不能再伪装成 mapped_config。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        ExecutionReport,
        FieldMappingArtifact,
        FieldMappingRow,
        StepResult,
        StepStatus,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
    )
    report = ExecutionReport(
        plan_id="button-field-mapping",
        results=(
            StepResult(
                step_id="field-mapping",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=FieldMappingArtifact(
                    item_count=1,
                    mappings=(
                        FieldMappingRow(
                            original_field="alarm_name",
                            standard_field="事件名称",
                            match_status="匹配成功",
                        ),
                    ),
                    download_kind="mapped_sub_rules",
                    download_content="mapped-rules-base64",
                ),
                message="字段映射完成",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    file_names = {file["name"] for file in captured["files"]}
    assert "fieldmapped_subrules_20260818_1006.txt" in file_names
    assert "button-field-mapping_mapped_sub_rules.txt" not in file_names
    assert len(captured["messages"]) == 3
    assert "已写入解析子规则" in captured["messages"][2]["content"]
    assert "fieldmapped_subrules_20260818_1006.txt" in captured["messages"][2]["content"]


def test字段映射无可下载产物时不发送下载消息(monkeypatch):
    """download_kind 为空时只渲染映射表和汇总，不产生任何下载文件或下载消息。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        ExecutionReport,
        FieldMappingArtifact,
        FieldMappingRow,
        StepResult,
        StepStatus,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-mapping-only",
        results=(
            StepResult(
                step_id="fm-1",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=FieldMappingArtifact(
                    item_count=1,
                    mappings=(
                        FieldMappingRow(
                            original_field="alpha",
                            standard_field="标准_alpha",
                            match_status="匹配成功",
                        ),
                    ),
                ),
                message="字段映射完成",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["dataframes"]) == 1
    assert captured["files"] == []
    assert len(captured["messages"]) == 2
    assert captured["messages"][0]["elements"] == []
    assert len(captured["messages"][1]["elements"]) == 1
    assert "点击下载" not in captured["messages"][0]["content"]


def test威胁映射产物渲染为表格(monkeypatch):
    """threat_mapping 产物落表（原始值/映射值/类型），不只剩一行成功文案（回归 #31）。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        ExecutionReport,
        StepResult,
        StepStatus,
        ThreatMappingArtifact,
        ThreatMappingRow,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
    )
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

    assert len(captured["messages"]) == 3
    assert captured["messages"][0]["elements"] == []
    assert len(captured["messages"][1]["elements"]) == 1
    assert len(captured["messages"][2]["elements"]) == 1
    assert len(captured["dataframes"]) == 1
    table = captured["dataframes"][0]["data"]
    assert list(table.columns) == ["mappingType", "orgValue", "mappingValue"]
    assert set(table["orgValue"]) == {"attack", "scan"}
    assert set(table["mappingValue"]) == {"恶意活动", "扫描"}
    file_names = {f["name"] for f in captured["files"]}
    assert "threatmapping_20260818_1006.xlsx" in file_names
    assert "plan-threat_threat_mapping.xlsx" not in file_names
    threat_file = next(
        f for f in captured["files"] if f["name"] == "threatmapping_20260818_1006.xlsx"
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
    from contracts.planner_models import (
        EnumValuesArtifact,
        ExecutionReport,
        StepResult,
        StepStatus,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
    )
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

    assert len(captured["messages"]) == 3
    assert captured["messages"][0]["elements"] == []
    assert len(captured["messages"][1]["elements"]) == 1
    assert len(captured["messages"][2]["elements"]) == 1
    assert len(captured["dataframes"]) == 1
    assert set(captured["dataframes"][0]["data"]["枚举值"]) == {"attack", "scan"}
    file_names = {f["name"] for f in captured["files"]}
    assert "enumvalues_20260818_1006.json" in file_names
    assert "plan-enum_enum_values.json" not in file_names
    enum_file = next(f for f in captured["files"] if f["name"] == "enumvalues_20260818_1006.json")
    enum_data = json.loads(enum_file["content"].decode("utf-8"))
    assert set(enum_data) == {"field", "regex", "original_log", "value"}
    assert enum_data["value"] == ["attack", "scan"]


def test日志类型提取恢复真实分类详情样本和规则动作(monkeypatch):
    """真实分类结构必须渲染摘要与样本，不能把顶层汇总字段显示成空表。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        ExecutionReport,
        LogClassificationArtifact,
        StepResult,
        StepStatus,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
        raising=False,
    )
    report = ExecutionReport(
        plan_id="plan-log",
        results=(
            StepResult(
                step_id="log-1",
                operation_type="log_parse",
                status=StepStatus.SUCCESS,
                artifact=LogClassificationArtifact(
                    item_count=3,
                    classification={
                        "status": "SUCCESS",
                        "categorical_features": "在日志头中",
                        "Diversion_method": "在日志头中",
                        "log_format": "日志头+KV",
                        "feature_field": "__header__",
                        "feature_count": 3,
                        "classification_details": [
                            {
                                "logtype": "AUDIT",
                                "matched_regex": "AUDIT",
                                "meaning": "审计日志",
                                "real_samples": ["AUDIT: alarm_name=login"],
                            },
                            {
                                "logtype": "IPS",
                                "matched_regex": "IPS",
                                "meaning": "入侵防护日志",
                                "real_samples": ["IPS: alarm_name=attack"],
                            },
                            {
                                "logtype": "RUN_INFO",
                                "matched_regex": "RUN_INFO",
                                "meaning": "运行信息日志",
                                "real_samples": ["RUN_INFO: result=success"],
                            },
                        ],
                    },
                ),
                message="步骤执行成功",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["messages"]) == 2
    assert captured["messages"][0]["elements"] == []
    assert len(captured["messages"][1]["elements"]) == 1
    assert len(captured["dataframes"]) == 0
    content = captured["messages"][0]["content"]
    assert "### 📊 分类详情" in content
    assert "AUDIT" in content
    assert "IPS" in content
    assert "RUN_INFO" in content
    assert "AUDIT: alarm_name=login" in content
    assert "IPS: alarm_name=attack" in content
    assert "RUN_INFO: result=success" in content
    assert "status" not in content
    assert "feature_count" not in content
    assert "classification_details" not in content
    assert [action.name for action in captured["messages"][0]["actions"]] == [
        "apply_field_mapping",
        "export_rules",
        "export_sub_rules",
    ]
    file_names = {f["name"] for f in captured["files"]}
    assert "logclassification_20260818_1006.json" in file_names
    assert "plan-log_log_classification.json" not in file_names
    log_file = next(
        f for f in captured["files"] if f["name"] == "logclassification_20260818_1006.json"
    )
    log_data = json.loads(log_file["content"].decode("utf-8"))
    assert log_data["classification_details"][0]["logtype"] == "AUDIT"
    assert log_data["classification_details"][0]["real_samples"] == [
        "AUDIT: alarm_name=login"
    ]


def test表格块与步骤bullet之间用空行分隔(monkeypatch):
    """#195：markdown 表格/详情块前后补空行，GFM 不再把表格压成 bullet 的 lazy continuation。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        ConfigExportArtifact,
        EventAnnotationRow,
        ExecutionReport,
        FieldMappingArtifact,
        FieldMappingRow,
        LogClassificationArtifact,
        StepResult,
        StepStatus,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
    )
    report = ExecutionReport(
        plan_id="plan-spacing",
        results=(
            StepResult(
                step_id="fm-1",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=FieldMappingArtifact(
                    item_count=1,
                    mappings=(
                        FieldMappingRow(
                            original_field="src_ip",
                            standard_field="源IP",
                            match_status="匹配成功",
                        ),
                    ),
                    event_annotations=(
                        EventAnnotationRow(
                            rule_name="r1", event_name="网络攻击", event_level="提醒"
                        ),
                    ),
                ),
                message="字段映射完成",
            ),
            StepResult(
                step_id="log-1",
                operation_type="log_parse",
                status=StepStatus.SUCCESS,
                artifact=LogClassificationArtifact(
                    item_count=1,
                    classification={"status": "SUCCESS"},
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

    assert len(captured["messages"]) == 4
    assert captured["messages"][0]["elements"] == []
    assert [element.element_type for element in captured["messages"][1]["elements"]] == [
        "dataframe"
    ]
    assert all(
        [element.element_type for element in message["elements"]] == ["file"]
        for message in captured["messages"][2:]
    )
    content = captured["messages"][0]["content"]
    # 标注表格块与其前面的 bullet 之间有空行
    assert "（field_mapping）：字段映射完成\n\n🏷️" in content
    # 表格块与其后继 bullet 之间有空行（表格不被吞进列表项）
    assert "| r1 | 网络攻击 | 提醒 | — | — |\n\n- ✅ `log-1`" in content
    # 日志分类详情块首行与其前面的 bullet 之间有空行
    assert "（log_parse）：步骤执行成功\n\n## 🔍 日志解析结果" in content


def test威胁链等待期间只把空白威胁列显示为生成中():
    from web.plan_renderer import build_execution_report_content
    from contracts.planner_models import (
        EventAnnotationRow,
        ExecutionReport,
        FieldMappingArtifact,
        StepResult,
        StepStatus,
    )

    report = ExecutionReport(
        plan_id="pending-threat-report",
        results=(
            StepResult(
                step_id="field-mapping",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=FieldMappingArtifact(
                    item_count=0,
                    mappings=(),
                    event_annotations=(
                        EventAnnotationRow(
                            rule_name="threat-rule",
                            event_name="网络攻击",
                            event_level="提醒",
                        ),
                        EventAnnotationRow(
                            rule_name="normal-rule",
                            event_name="审计事件",
                            event_level="信息",
                        ),
                    ),
                ),
                message="字段映射完成",
            ),
        ),
    )

    content = build_execution_report_content(report, threat_pending=True)

    assert "| threat-rule | 网络攻击 | 提醒 | ⏳ 生成中 | ⏳ 生成中 |" in content
    assert "| normal-rule | 审计事件 | 信息 | — | — |" in content


def test多产物复合计划按汇总表格下载纵向发送(monkeypatch):
    """#195：汇总先发、表格逐条纵向展示，下载文件随后独立发送。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        ConfigExportArtifact,
        EnumValuesArtifact,
        ExecutionReport,
        StepResult,
        StepStatus,
        ThreatMappingArtifact,
        ThreatMappingRow,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
    )
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
                artifact=ConfigExportArtifact(
                    item_count=1,
                    content="config-text",
                    download_kind="threatmapping_config",
                ),
                message="威胁映射已填充到目标字段",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    element_types = [
        [element.element_type for element in message["elements"]]
        for message in captured["messages"]
    ]
    assert element_types == [[], ["dataframe"], ["dataframe"], ["file"], ["file"], ["file"]]
    assert "plan-compound" in captured["messages"][0]["content"]
    assert all(types.count("dataframe") <= 1 for types in element_types)
    assert len(captured["dataframes"]) == 2
    file_names = {f["name"] for f in captured["files"]}
    assert file_names == {
        "threatmapping_config_20260818_1006.txt",
        "enumvalues_20260818_1006.json",
        "threatmapping_20260818_1006.xlsx",
    }


def test完整威胁链成功后只下载映射表和最终配置(monkeypatch):
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        ConfigExportArtifact,
        EnumValuesArtifact,
        ExecutionReport,
        StepResult,
        StepStatus,
        ThreatMappingArtifact,
        ThreatMappingRow,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 9, 10, 9, 30)),
    )

    def config_result(step_id: str, operation_type: str, content: str, kind: str):
        return StepResult(
            step_id=step_id,
            operation_type=operation_type,
            status=StepStatus.SUCCESS,
            artifact=ConfigExportArtifact(
                item_count=1, content=content, download_kind=kind
            ),
            message="步骤执行成功",
        )

    report = ExecutionReport(
        plan_id="plan-threat-chain",
        results=(
            StepResult(
                step_id="threat-chain-enum",
                operation_type="enum_extract",
                status=StepStatus.SUCCESS,
                artifact=EnumValuesArtifact(item_count=1, values=("scan",)),
                message="步骤执行成功",
            ),
            StepResult(
                step_id="threat-chain-map",
                operation_type="threat_mapping",
                status=StepStatus.SUCCESS,
                artifact=ThreatMappingArtifact(
                    item_count=1,
                    mappings=(
                        ThreatMappingRow(
                            mappingType="EQUAL",
                            orgValue="scan",
                            mappingValue="扫描",
                        ),
                    ),
                ),
                message="步骤执行成功",
            ),
            config_result(
                "threat-chain-replace", "delete_fields", "after-delete", "field_adjusted_config"
            ),
            config_result(
                "threat-chain-add", "add_fields", "after-add", "field_adjusted_config"
            ),
            config_result(
                "threat-chain-fill", "fill", "final-config", "threatmapping_config"
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert {item["name"] for item in captured["files"]} == {
        "threatmapping_20260910_0930.xlsx",
        "threatmapping_config_20260910_0930.txt",
    }


def test威胁链失败时不下载已产生的中间文件(monkeypatch):
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        EnumValuesArtifact,
        ExecutionReport,
        StepResult,
        StepStatus,
    )

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-threat-chain-failed",
        results=(
            StepResult(
                step_id="threat-chain-enum",
                operation_type="enum_extract",
                status=StepStatus.SUCCESS,
                artifact=EnumValuesArtifact(item_count=1, values=("scan",)),
                message="步骤执行成功",
            ),
            StepResult(
                step_id="threat-chain-map",
                operation_type="threat_mapping",
                status=StepStatus.FAILED,
                error_code="threat_mapping_failed",
                message="映射失败",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert captured["files"] == []
    assert len(captured["dataframes"]) == 1


def test无产物报告只发送汇总消息(monkeypatch):
    """#195：没有表格或下载产物时，不生成空的附加消息。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import ExecutionReport, StepResult, StepStatus

    captured = _mount_chainlit_captures(monkeypatch, renderer)
    report = ExecutionReport(
        plan_id="plan-no-artifact",
        results=(
            StepResult(
                step_id="blocked-1",
                operation_type="field_mapping",
                status=StepStatus.NEEDS_INPUT,
                message="请先上传主数据",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(captured["messages"]) == 1
    assert captured["messages"][0]["elements"] == []
    assert "blocked-1" in captured["messages"][0]["content"]


def test信息型作答渲染为guidance答案而非能力说明(monkeypatch):
    """guidance 携带 answer 时直接渲染事实答案；无 answer 时回退能力说明（#149）。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import PlanDecision

    captured = {"messages": []}

    class _Message:
        """记录消息文案。"""

        def __init__(self, content, elements=None, actions=None):
            self.content = content

        async def send(self):
            captured["messages"].append(self.content)

    monkeypatch.setattr(renderer.cl, "Message", _Message)

    answered = PlanDecision.model_validate(
        {
            "decision": "guidance",
            "answer": "当前子规则事件标注：AUDIT_kv_子规则=审计事件（信息）、IPS_kv_子规则=未标注。",
        }
    )
    asyncio.run(renderer.render_decision(answered))

    capabilities = PlanDecision.model_validate(
        {"decision": "guidance", "guidance_code": "capabilities"}
    )
    asyncio.run(renderer.render_decision(capabilities))

    assert captured["messages"][0].startswith("📖 当前子规则事件标注")
    assert "AUDIT_kv_子规则=审计事件（信息）" in captured["messages"][0]
    assert "我可以处理" in captured["messages"][1]


def test跨轮报告锚点更新同一消息且保存最终表(monkeypatch):
    """成功威胁填充只更新原消息，供下一轮继续复用同一锚点。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import (
        EventAnnotationRow,
        ExecutionReport,
        FieldMappingArtifact,
        StepResult,
        StepStatus,
    )

    store = {}

    class UserSession:
        def get(self, key):
            return store.get(key)

        def set(self, key, value):
            store[key] = value

    class Message:
        content = ""
        updates = 0

        async def update(self):
            self.updates += 1

    monkeypatch.setattr(renderer.cl, "user_session", UserSession())
    primary = ExecutionReport(
        plan_id="field-mapping",
        results=(
            StepResult(
                step_id="field-mapping",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=FieldMappingArtifact(
                    item_count=0,
                    mappings=(),
                    event_annotations=(
                        EventAnnotationRow(
                            rule_name="threat-rule",
                            event_name="网络攻击",
                            event_level="提醒",
                        ),
                    ),
                ),
            ),
        ),
    )
    chain = ExecutionReport(
        plan_id="explicit-threat",
        results=(
            StepResult(
                step_id="threat-chain-fill",
                operation_type="fill",
                status=StepStatus.SUCCESS,
                changed_count=1,
            ),
        ),
    )
    final_config = [
        {
            "name": "threat-rule",
            "normalize": [{"index": "威胁类型", "mappings": []}],
            "parser": {
                "filter": [
                    {"name": "addFields", "fields": {"威胁类型": "其他"}}
                ]
            },
        }
    ]
    message = Message()
    renderer.remember_primary_report(message, primary)

    updated = asyncio.run(renderer.refresh_primary_report_anchor(chain, final_config))

    assert updated is True
    assert message.updates == 1
    assert "—（固定值）" in message.content
    assert "其他" in message.content
    assert store[renderer._PRIMARY_REPORT_ANCHOR_KEY][0] is message
