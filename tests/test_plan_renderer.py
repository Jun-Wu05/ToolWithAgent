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
