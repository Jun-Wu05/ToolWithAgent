"""#177 标准字段与对象组合合法性回归。

产物级验证：解码字段映射导出的 Base64 配置，系统新写入的每条非空
normalize.field/entity 都能解析为标准字段目录中的合法组合；【事件名称】/
【事件级别】固定归属「事件」；目录外模型输出被降级为未匹配而非写入。
"""

from __future__ import annotations

import asyncio
import base64
import json

from application.adapters.field_mapping import FieldMappingAdapter
from application.execution import ExecutionContext
from application.session_projection import build_session_facts
from contracts.planner_models import FieldMappingStep, StepStatus
from agent.tools.rule_generator.field_mapping import (
    canonical_field_entity,
    resolve_standard_field,
)
from factories import make_session_state


class _MappingRunner:
    """返回一条目录内变体 + 一条目录外名称的映射假件。"""

    async def run(self, fields, **_kwargs):
        return [
            # 英文变体 + 前后空白：目录可唯一定位 → 规范化为 源地址
            {"原始字段名": "attack_type", "系统属性名称": "  src_address ", "匹配状态": "匹配成功"},
            # 目录外名称：不得写入配置
            {"原始字段名": "bad_field", "系统属性名称": "天眼ID", "匹配状态": "匹配成功"},
        ]


def _decoded_rules(artifact) -> list[dict]:
    """解码导出产物为规则列表。"""
    return json.loads(base64.b64decode(artifact.download_content))


def test产物级导出字段与对象全部属于目录(monkeypatch):
    """映射 + 事件标注产物解码后逐条校验目录合法性（issue #177 验收 5）。"""
    import agent.tools.rule_generator as rule_generator

    generated = [
        {
            "name": "rule-x",
            "normalize": [
                {"index": "attack_type"},
                {"index": "bad_field"},
            ],
        }
    ]
    monkeypatch.setattr(
        rule_generator,
        "generate_sub_rules",
        lambda classification, all_logs_str, rule_source_fields: generated,
    )
    session = make_session_state(
        log_classification={"classification_details": [{"logtype": "x"}]},
        raw_log_lines=["attack_type=暴力破解 bad_field=1"],
        rule_source_fields={
            "product": "产品",
            "log_vendor": "厂商",
            "data_source": "产品(厂商)",
        },
    )

    result = asyncio.run(
        FieldMappingAdapter(
            team=None,
            batch_runner=_MappingRunner(),
            candidate_retriever=lambda fields: {},
            event_classifier=lambda _: json.dumps(
                {"results": [{"rule_name": "rule-x", "event_name": "网络攻击", "group": "threat"}]}
            ),
        ).execute(
            FieldMappingStep(
                step_id="mapping-catalog",
                type="field_mapping",
                source_ref="session.fields",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    rules = _decoded_rules(result.artifact)
    assert [rule["name"] for rule in rules] == ["rule-x"]
    entries = {entry["index"]: entry for entry in rules[0]["normalize"]}

    # 目录内变体规范化写入（src_address → 源地址/流量）
    assert entries["attack_type"]["field"] == "源地址"
    assert entries["attack_type"]["entity"] == "流量"
    # 目录外名称降级清空，不写入非法组合
    assert entries["bad_field"]["field"] is None
    assert entries["bad_field"]["entity"] is None
    # 事件固定字段归属「事件」（#177 核心回归，原缺陷为 entity=日志）
    assert entries["事件名称"]["field"] == "event_name"
    assert entries["事件名称"]["entity"] == "事件"
    assert entries["事件级别"]["field"] == "event_level"
    assert entries["事件级别"]["entity"] == "事件"

    # 全量校验：所有非空 field/entity 均为目录合法组合
    for entry in rules[0]["normalize"]:
        field_name = str(entry.get("field") or "").strip()
        if not field_name:
            continue
        record = resolve_standard_field(field_name)
        assert record is not None, f"目录外字段被写入: {field_name}"
        assert entry["entity"] == canonical_field_entity(record), (
            f"对象与目录不一致: {field_name} -> {entry['entity']}"
        )


def test校验器变体名称规范化为目录规范名():
    """英文/空白变体在目录可唯一定位时改写为规范系统属性名称。"""
    from agent.tools.standard_mapper import _validate_and_correct_mapping

    corrected = _validate_and_correct_mapping(
        {"原始字段名": "src_ip", "系统属性名称": " src_address ", "匹配状态": "匹配成功"}
    )
    assert corrected["系统属性名称"] == "源地址"
    assert "规范化" in corrected["_校正原因"]

    exact = _validate_and_correct_mapping(
        {"原始字段名": "src_ip", "系统属性名称": "源地址", "匹配状态": "匹配成功"}
    )
    assert exact["系统属性名称"] == "源地址"


def test校验器目录外名称降级为未匹配():
    """目录外名称不得写入配置：降级并给出可定位原因。"""
    from agent.tools.standard_mapper import _validate_and_correct_mapping

    corrected = _validate_and_correct_mapping(
        {"原始字段名": "x", "系统属性名称": "天眼ID", "匹配状态": "匹配成功"}
    )
    assert corrected["系统属性名称"] == "未匹配"
    assert corrected["匹配状态"] == "未匹配"
    assert "天眼ID" in corrected["_校正原因"]
