"""Issue #172：syslog 头 + JSON body-key 路线的应用链路回归。"""

from __future__ import annotations

import asyncio
import base64
import json


SYSLOG_JSON_LINE = (
    "<1068>Sep 01 13:50:00 audit-host Audit REDIS: "
    '{"app_protocol":"REDIS","src_ip":"10.0.0.1","action":"query"}'
)


def _classify_body_key(monkeypatch) -> dict:
    """经 Agent 公开 headless 门面生成 body-key 分类，不访问外部模型。"""
    import agent.tools.pipeline.log_classifier as log_classifier
    from agent.tools import classify_log_features_headless

    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *args, **kwargs: json.dumps(
            {
                "status": "PARTIAL",
                "feature_field": "app_protocol",
                "classification_details": [
                    {"logtype": "REDIS", "meaning": "Redis 审计日志"}
                ],
            },
            ensure_ascii=False,
        ),
    )
    return json.loads(
        classify_log_features_headless(
            SYSLOG_JSON_LINE,
            "json",
            "日志头+JSON",
            "app_protocol",
            json.dumps(
                {
                    "format": "json",
                    "format_detail": "日志头+JSON",
                    "feature_field": "app_protocol",
                    "header_end_marker": ": ",
                },
                ensure_ascii=False,
            ),
            ": ",
        )
    )


def test_body_key分类保留完整sample并提供可解析json_real_samples(monkeypatch) -> None:
    classification = _classify_body_key(monkeypatch)

    detail = classification["classification_details"][0]
    assert detail["sample"] == SYSLOG_JSON_LINE
    assert json.loads(detail["real_samples"]) == {
        "app_protocol": "REDIS",
        "src_ip": "10.0.0.1",
        "action": "query",
    }


def test_body_key分类可由真实导出adapter生成子规则(monkeypatch) -> None:
    from application.adapters.export import ExportAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import ExportStep, StepStatus

    classification = _classify_body_key(monkeypatch)
    session = {
        "log_classification": classification,
        "raw_log_lines": [SYSLOG_JSON_LINE],
        "rule_source_fields": {
            "product": "测试产品",
            "log_vendor": "测试厂商",
            "data_source": "测试产品(测试厂商)",
        },
    }
    result = asyncio.run(
        ExportAdapter().execute(
            ExportStep(
                step_id="export-sub-rules",
                type="export",
                source_ref="session.log_classification.sub_rules",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    rules = json.loads(base64.b64decode(result.artifact.content).decode("utf-8"))
    assert len(rules) == 1
    assert rules[0]["normalize"]


def test_body_key分类可由真实字段映射adapter原子写回(monkeypatch) -> None:
    from application.adapters.field_mapping import FieldMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import FieldMappingStep, StepStatus

    class MappingRunner:
        async def run(self, fields, **kwargs):
            return [
                {
                    "原始字段名": field,
                    "系统属性名称": f"标准_{field}",
                    "匹配状态": "匹配成功",
                }
                for field in fields
            ]

    classification = _classify_body_key(monkeypatch)
    session = {
        "log_classification": classification,
        "raw_log_lines": [SYSLOG_JSON_LINE],
        "rule_source_fields": {
            "product": "测试产品",
            "log_vendor": "测试厂商",
            "data_source": "测试产品(测试厂商)",
        },
    }
    context = ExecutionContext(
        session=session,
        session_facts=build_session_facts(session),
    )
    result = asyncio.run(
        FieldMappingAdapter(
            team=None,
            batch_runner=MappingRunner(),
            object_map_loader=lambda _: {},
            event_classifier=lambda _: json.dumps({"results": []}),
        ).execute(
            FieldMappingStep(
                step_id="field-mapping",
                type="field_mapping",
                source_ref="session.fields",
            ),
            context,
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert session["mapped_sub_rules"]
    assert session["sub_rule_mapping_results"]
    assert result.artifact.download_kind == "mapped_sub_rules"
    assert result.artifact.download_content
