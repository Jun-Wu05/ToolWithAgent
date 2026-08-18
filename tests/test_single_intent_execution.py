"""七类单步操作通过统一执行器运行的回归门禁。"""

import asyncio
import json
import logging
import time

from web.execution_adapters import create_default_adapters
from web.plan_executor import ExecutionContext, PlanExecutor
from contracts.planner_models import PlanDecision, StepStatus
from contracts.session_facts import build_session_facts


class _StaticMember:
    """返回固定结构化响应的专业 Agent 测试替身。"""

    def __init__(self, name: str, response: str) -> None:
        """保存成员名称与响应；测试只替换外部模型，不替换执行核心。"""
        self.name = name
        self._response = response

    def run(self, model_input: str) -> str:
        """返回预设响应；输入由真实适配器负责构造。"""
        return self._response


class _Team:
    """提供按名称选择的专业 Agent 成员集合。"""

    def __init__(self, *members: _StaticMember) -> None:
        """保存测试所需的最小成员列表。"""
        self.members = list(members)


def _execute_single_step(session: dict, step: dict, team=None):
    """通过真实 PlanExecutor 执行一个类型化步骤并返回执行报告。"""
    decision = PlanDecision.model_validate(
        {"decision": "execute", "plan_id": f"single-{step['type']}", "steps": [step]}
    )
    return asyncio.run(
        PlanExecutor(create_default_adapters(team)).execute(
            decision,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )


def test日志类型提取单步可运行(monkeypatch):
    """日志分类只替换专业模型输出，状态推进仍经过统一执行核心。"""
    import agent.tools.pipeline.log_classifier as log_classifier
    import agent.tools.pipeline.log_format_identifier as log_format_identifier
    import agent.tools.pipeline.log_sample_filler as log_sample_filler

    monkeypatch.setattr(
        log_format_identifier,
        "_do_identify_log_format",
        lambda logs_text: json.dumps(
            {
                "format": "key_value",
                "format_detail": "键值日志",
                "feature_field": "event_type3",
                "header_end_marker": "",
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(
        log_classifier,
        "_do_classify_log_features",
        lambda *args: json.dumps({"攻击日志": {"feature": "attack"}}, ensure_ascii=False),
    )
    monkeypatch.setattr(log_sample_filler, "fill_sample_logs", lambda classification, logs_text: classification)
    session = {"raw_log_lines": ["event_type3=attack src=10.0.0.1"]}

    report = _execute_single_step(
        session,
        {"step_id": "log", "type": "log_parse"},
    )

    assert report.status == StepStatus.SUCCESS
    assert session["log_classification"] == {"攻击日志": {"feature": "attack"}}


def test字段映射单步可运行(monkeypatch):
    """字段映射使用 SessionFacts 字段并调用明确命名的专业 Agent。"""
    import web.input_builder as input_builder

    monkeypatch.setattr(input_builder, "_pre_query_field_candidates", lambda fields: "")
    member = _StaticMember(
        "FieldMappingAgent",
        json.dumps(
            [
                {
                    "原始字段名": "event_type3",
                    "系统属性名称": "event_type3_standard",
                    "匹配状态": "匹配成功",
                }
            ],
            ensure_ascii=False,
        ),
    )
    session = {"decoded_fields": ["event_type3"]}

    report = _execute_single_step(
        session,
        {"step_id": "mapping", "type": "field_mapping", "source_ref": "session.fields"},
        _Team(member),
    )

    assert report.status == StepStatus.SUCCESS
    assert session["last_mapping_data"][0]["原始字段名"] == "event_type3"


def test枚举提取单步可运行(monkeypatch):
    """枚举提取只替换正则生成模型，采样、校验和提取使用真实领域函数。"""
    import agent.tools.pipeline.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "_call_llm_direct",
        lambda *args, **kwargs: json.dumps(
            {"field": "event_type3", "regex": r"event_type3=(\w+)"}
        ),
    )
    session = {
        "raw_log_lines": ["event_type3=attack src=10.0.0.1", "event_type3=scan src=10.0.0.2"],
        "decoded_fields": ["event_type3"],
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_type3",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.SUCCESS
    assert set(report.results[0].artifact.values) == {"attack", "scan"}


def test枚举提取从原始日志读取未进入字段映射列表的event_name(monkeypatch):
    """目标字段来自原始日志内容时，不要求它先出现在 available_fields。"""
    import agent.tools.pipeline.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {"field": "event_name", "regex": r'"event_name"\s*:\s*"([^"]+)"'},
            ensure_ascii=False,
        ),
    )
    session = {
        "raw_log_lines": [
            '{"data":{"event_name":"login"}}',
            '{"data":{"event_name":"logout"}}',
        ],
        "decoded_fields": ["src"],
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_name",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.SUCCESS
    assert set(report.results[0].artifact.values) == {"login", "logout"}


def test枚举提取模型返回非JSON时失败关闭(monkeypatch):
    """模型返回非合法 JSON 时返回 enum_regex_invalid，不静默成功（回归 #37）。"""
    import agent.tools.pipeline.llm_client as llm_client

    monkeypatch.setattr(llm_client, "_call_llm_direct", lambda *a, **kw: "这不是JSON")
    session = {
        "raw_log_lines": ["event_type3=attack src=10.0.0.1"],
        "decoded_fields": ["event_type3"],
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_type3",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].error_code == "enum_regex_invalid"
    assert report.results[0].artifact is None


def test枚举提取字段不一致时失败关闭(monkeypatch):
    """模型返回的 field 与目标字段不一致时失败关闭（回归 #37）。"""
    import agent.tools.pipeline.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps({"field": "别的字段", "regex": r"(\w+)"}, ensure_ascii=False),
    )
    session = {
        "raw_log_lines": ["event_type3=attack src=10.0.0.1"],
        "decoded_fields": ["event_type3"],
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_type3",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].error_code == "enum_regex_invalid"


def test枚举提取正则无法匹配时失败关闭(monkeypatch):
    """生成的正则校验与修复均失败时返回 enum_regex_no_match（回归 #37）。"""
    import agent.tools.enum_extract_tool as enum_tool
    import agent.tools.pipeline.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps({"field": "event_type3", "regex": r"event_type3=(\w+)"}, ensure_ascii=False),
    )
    monkeypatch.setattr(enum_tool, "validate_regex_with_stats", lambda *a, **kw: {"valid": False})
    monkeypatch.setattr(enum_tool, "validate_and_fix_regex", lambda *a, **kw: {"valid": False})
    session = {
        "raw_log_lines": ["event_type3=attack src=10.0.0.1"],
        "decoded_fields": ["event_type3"],
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_type3",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].error_code == "enum_regex_no_match"


def test枚举提取空结果时失败关闭(monkeypatch):
    """正则合法但提取不到枚举值时返回 enum_extract_empty（回归 #37）。"""
    import agent.tools.enum_extract_tool as enum_tool
    import agent.tools.pipeline.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps({"field": "event_type3", "regex": r"event_type3=(\w+)"}, ensure_ascii=False),
    )
    monkeypatch.setattr(enum_tool, "validate_regex_with_stats", lambda *a, **kw: {"valid": True})
    monkeypatch.setattr(enum_tool, "extract_enum_with_field", lambda *a, **kw: {"value": []})
    session = {
        "raw_log_lines": ["event_type3=attack src=10.0.0.1"],
        "decoded_fields": ["event_type3"],
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_type3",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].error_code == "enum_extract_empty"


def test枚举提取无日志时在适配器调用前拦截():
    """无日志时执行器以 logs_required 拦截，不进入适配器（回归 #37）。"""
    session = {}

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_type3",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "logs_required"


def test枚举提取失败不被旧枚举结果掩盖(monkeypatch):
    """session 残留旧 last_enum_extract_result 时，本次失败仍报失败，不误报成功（回归 #37）。"""
    import agent.tools.pipeline.llm_client as llm_client

    monkeypatch.setattr(llm_client, "_call_llm_direct", lambda *a, **kw: "bad-json")
    session = {
        "raw_log_lines": ["event_type3=attack src=10.0.0.1"],
        "decoded_fields": ["event_type3"],
        "last_enum_extract_result": {"value": ["旧值不得掩盖失败"]},
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "enum",
            "type": "enum_extract",
            "target_field": "event_type3",
            "source_ref": "session.logs",
        },
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].artifact is None
    # 旧值既未被当作本次成功产物上报，也未被清空。
    assert session["last_enum_extract_result"]["value"] == ["旧值不得掩盖失败"]


def test威胁类型映射单步可运行():
    """用户显式值可直接进入威胁映射，不读取旧枚举结果。"""
    member = _StaticMember(
        "ThreatAgent",
        json.dumps(
            [
                {
                    "mappingType": "EQUAL",
                    "orgValue": "attack",
                    "mappingValue": "恶意活动",
                }
            ],
            ensure_ascii=False,
        ),
    )
    session = {"last_enum_extract_result": {"value": ["不得读取"]}}

    report = _execute_single_step(
        session,
        {
            "step_id": "threat",
            "type": "threat_mapping",
            "source_ref": "user.values",
            "values": ["attack"],
        },
        _Team(member),
    )

    assert report.status == StepStatus.SUCCESS
    assert session["last_threat_data"][0]["orgValue"] == "attack"


def test枚举填充单步可运行():
    """Base64 解码配置可直接填充，无需先生成 mapped_sub_rules。"""
    session = {
        "decoded_data": {
            "name": "uploaded-rule",
            "normalize": [{"index": "event_type3", "mappings": []}],
        },
        "enum_preview": [
            {
                "目标字段": "event_type3",
                "mappingType": "EQUAL",
                "orgValue": "attack",
                "mappingValue": "攻击",
            }
        ],
    }

    execution_started_at = time.monotonic()
    report = _execute_single_step(
        session,
        {
            "step_id": "fill",
            "type": "fill",
            "fill_kind": "enum",
            "target_fields": ["event_type3"],
            "source_ref": "session.enum_mapping_table",
            "config_ref": "session.decoded_config",
        },
    )
    execution_elapsed = time.monotonic() - execution_started_at

    assert report.status == StepStatus.SUCCESS
    assert execution_elapsed < 1.0
    assert session["decoded_data"]["normalize"][0]["mappings"][0]["orgValue"] == "attack"


def test取消映射单步可运行():
    """取消映射修改显式配置来源并返回完整可下载配置。"""
    session = {
        "decoded_data": {
            "normalize": [
                {
                    "index": "event_type3",
                    "mappings": [
                        {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}
                    ],
                }
            ]
        }
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "remove",
            "type": "remove_mapping",
            "target_fields": ["event_type3"],
            "config_ref": "session.decoded_config",
        },
    )

    assert report.status == StepStatus.SUCCESS
    assert session["decoded_data"]["normalize"][0]["mappings"] == []
    assert report.results[0].artifact.content


def test导出单步可运行():
    """完整解码配置可以显式来源直接导出，不误入日志规则导出分支。"""
    session = {
        "decoded_data": {
            "name": "uploaded-rule",
            "normalize": [{"index": "event_type3", "mappings": []}],
        }
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "export",
            "type": "export",
            "source_ref": "session.decoded_config",
        },
    )

    assert report.status == StepStatus.SUCCESS
    assert report.results[0].artifact.item_count == 1
    assert report.results[0].artifact.content


def test执行前拦截日志包含稳定追踪字段(caplog):
    """日志必须说明请求了什么配置来源以及当前实际有哪些来源。"""
    caplog.set_level(logging.INFO, logger="plan_executor")
    session = {
        "decoded_data": {
            "normalize": [{"index": "event_type3", "mappings": []}],
        },
        "enum_preview": [{"目标字段": "event_type3"}],
    }

    report = _execute_single_step(
        session,
        {
            "step_id": "fill-step",
            "type": "fill",
            "fill_kind": "enum",
            "target_fields": ["event_type3"],
            "source_ref": "session.enum_mapping_table",
            "config_ref": "session.mapped_sub_rules",
        },
    )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert report.status == StepStatus.NEEDS_INPUT
    assert "plan_id=single-fill" in messages
    assert "step_id=fill-step" in messages
    assert "operation=fill" in messages
    assert "error_category=config_source_unavailable" in messages
    assert "required_config_ref=session.mapped_sub_rules" in messages
    assert "session.decoded_config" in messages


def test成功填充报告输出下载文件(monkeypatch):
    """成功产物必须使用类型契约中的 content 字段生成唯一下载文件。"""
    import web.plan_renderer as renderer
    from contracts.planner_models import ConfigExportArtifact, ExecutionReport, StepResult

    sent_messages = []

    class _File:
        """记录 Renderer 创建的下载文件参数。"""

        def __init__(self, *, name: str, content: bytes, mime: str) -> None:
            """保存文件元数据供断言，不触发真实 Chainlit。"""
            self.name = name
            self.content = content
            self.mime = mime

    class _Message:
        """记录 Renderer 发送的最终单条消息。"""

        def __init__(self, *, content: str, elements: list) -> None:
            """保存消息文本和元素列表。"""
            self.content = content
            self.elements = elements

        async def send(self) -> None:
            """模拟发送并记录消息。"""
            sent_messages.append(self)

    monkeypatch.setattr(renderer.cl, "File", _File)
    monkeypatch.setattr(renderer.cl, "Message", _Message)
    report = ExecutionReport(
        plan_id="render-fill",
        results=(
            StepResult(
                step_id="fill",
                operation_type="fill",
                status=StepStatus.SUCCESS,
                changed_count=1,
                artifact=ConfigExportArtifact(content="encoded-config", item_count=1),
                message="枚举映射已填充到目标字段",
            ),
        ),
    )

    asyncio.run(renderer.render_execution_report(report))

    assert len(sent_messages) == 1
    assert len(sent_messages[0].elements) == 1
    assert sent_messages[0].elements[0].content == b"encoded-config"
    assert sent_messages[0].elements[0].name == "render-fill_config.txt"
