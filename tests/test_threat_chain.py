"""#173 威胁类型链路编排集成测试：执行后续跑、失败语义、幂等与会话覆盖。"""

from __future__ import annotations

import asyncio
import json

import numpy as np

from agent.core import field_retriever
from application.threat_chain import (
    SESSION_OVERRIDE_KEY,
    run_threat_chain_after_mapping,
)
from contracts.planner_models import (
    AddFieldsStep,
    EventAnnotationRow,
    ExecutionReport,
    FieldMappingArtifact,
    FieldMappingRow,
    StepResult,
    StepStatus,
)
from contracts.session_artifacts import ThreatArtifactSlot


def _threat_rule(name: str) -> dict:
    """构造已标注威胁事件名称的子规则（addFields 绑定事件名称/级别）。"""
    return {
        "name": name,
        "normalize": [
            {"index": "attack_type", "mappings": []},
            {"index": "src_ip", "mappings": []},
        ],
        "parser": {
            "filter": [
                {
                    "name": "addFields",
                    "id": "",
                    "fields": {"事件名称": "网络攻击", "事件级别": "提醒"},
                }
            ]
        },
    }


def _mapping_report(rule_names=("威胁A", "威胁B")) -> ExecutionReport:
    """构造字段映射成功的主报告（含威胁子规则标注）。"""
    artifact = FieldMappingArtifact(
        item_count=1,
        mappings=(
            FieldMappingRow(
                **{
                    "原始字段名": "attack_type",
                    "系统属性名称": "源地址",
                    "匹配状态": "匹配成功",
                }
            ),
        ),
        event_annotations=tuple(
            EventAnnotationRow(rule_name=name, event_name="网络攻击", status="judged")
            for name in rule_names
        ),
    )
    return ExecutionReport(
        plan_id="mapping-run",
        results=(
            StepResult(
                step_id="field-mapping",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=artifact,
                message="字段映射完成",
            ),
        ),
    )


class _ThreatMember:
    """返回全量威胁映射的 ThreatAgent 替身。"""

    name = "ThreatAgent"

    def __init__(self, response: str) -> None:
        self.response = response

    def run(self, model_input: str) -> str:
        return self.response


class _Team:
    """单成员测试 Team 替身。"""

    def __init__(self, member) -> None:
        self.members = [member]


_FULL_MAPPING = json.dumps(
    [
        {"mappingType": "REGULAR", "orgValue": r"(?i).*暴力破解.*", "mappingValue": "暴力破解"},
        {"mappingType": "REGULAR", "orgValue": r"(?i).*端口扫描.*", "mappingValue": "端口扫描"},
    ],
    ensure_ascii=False,
)


def _mock_retrieval(monkeypatch) -> None:
    """候选检索假件：攻击字段与威胁类型记录同向（高分命中）。"""
    records = [{"系统属性名称": "威胁类型", "字段名称": "threat_type"}]
    embeddings = np.array([[1.0, 0.0]])
    monkeypatch.setattr(field_retriever, "_load_cache", lambda: (embeddings, records))
    monkeypatch.setattr(
        field_retriever,
        "_call_embedding_api",
        lambda texts: np.array([[1.0, 0.0] for _ in texts]),
    )


def _mock_enum_llm(monkeypatch, response=None) -> None:
    """枚举正则生成的直连模型假件（适配器构造时惰性导入 agent.tools）。

    默认按输入里的「目标字段」动态返回匹配该字段的 KV 正则，
    保证任意来源字段（含会话覆盖值）都能走通提取。
    """
    import re as re_module

    import agent.tools as tools

    def _call(model_input: str, **kwargs):
        if response is not None:
            return response
        matched = re_module.search(r"目标字段：(\S+)", model_input)
        target = matched.group(1) if matched else "attack_type"
        return json.dumps({"field": target, "regex": rf"{target}=([^\s]+)"})

    monkeypatch.setattr(tools, "call_llm_direct", _call)


def _chain_session() -> dict:
    """链路可运行的会话：原始日志 + 已标注威胁子规则。"""
    return {
        "raw_log_lines": [
            "attack_type=暴力破解 src_ip=1.1.1.1",
            "attack_type=端口扫描 src_ip=2.2.2.2",
        ],
        "mapped_sub_rules": [_threat_rule("威胁A"), _threat_rule("威胁B")],
    }


def _run(report, session, team):
    return asyncio.run(
        run_threat_chain_after_mapping(
            report=report,
            plan_steps=(),
            session=session,
            team=team,
            progress_sink=None,
        )
    )


def _threat_binding(rule: dict) -> str | None:
    """读取子规则 addFields 过滤器中威胁类型的绑定值（可能追加在任意过滤器）。"""
    for filter_item in rule.get("parser", {}).get("filter", []):
        value = filter_item.get("fields", {}).get("威胁类型")
        if value is not None:
            return value
    return None


def test自动链路全链成功并追加汇总行(monkeypatch):
    """四步全链：威胁子规则获得 威胁类型=%{attack_type} 绑定与值映射。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    session = _chain_session()
    report = _mapping_report()

    extended = _run(report, session, _Team(_ThreatMember(_FULL_MAPPING)))

    # 主报告结果保持不变，末尾追加链路成功步骤 + 🔗 汇总
    assert extended.results[0] is report.results[0]
    summary = extended.results[-1]
    assert summary.step_id == "threat-chain"
    assert summary.message.startswith("🔗 威胁类型链路已自动完成")
    assert "来源字段=attack_type" in summary.message

    for rule in session["mapped_sub_rules"]:
        threat_entries = [
            entry
            for entry in rule["normalize"]
            if entry.get("index") == "威胁类型"
        ]
        assert len(threat_entries) == 1
        assert len(threat_entries[0]["mappings"]) == 2
        assert _threat_binding(rule) == "%{attack_type}"


def test链路失败不阻塞字段映射成功报告(monkeypatch):
    """枚举正则生成失败 → 链路 ⚠️，主报告结果与状态不变。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch, response="不是JSON")
    session = _chain_session()

    extended = _run(_mapping_report(), session, _Team(_ThreatMember(_FULL_MAPPING)))

    assert len(extended.results) == 2
    assert extended.status == StepStatus.SUCCESS
    summary = extended.results[-1]
    assert summary.message.startswith("⚠️ 威胁类型链路未完全成功")
    assert "字段映射结果不受影响" in summary.message


def test全部待确认时只提示不跑链路():
    """无已判定威胁但有待确认 → ⚠️ 提示行，不执行任何链路步骤。"""
    session = _chain_session()
    artifact = FieldMappingArtifact(
        item_count=0,
        mappings=(),
        event_annotations=(
            EventAnnotationRow(rule_name="x", status="uncertain"),
        ),
    )
    report = ExecutionReport(
        plan_id="mapping-run",
        results=(
            StepResult(
                step_id="field-mapping",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                artifact=artifact,
                message="ok",
            ),
        ),
    )

    extended = _run(report, session, _Team(_ThreatMember(_FULL_MAPPING)))

    assert len(extended.results) == 2
    assert "待人工确认" in extended.results[-1].message
    # 未动会话产物
    assert session.get("latest_threat_artifact") is None


def test重跑幂等先删后加整体替换(monkeypatch):
    """第二次链路识别自产状态：先删后加，mappings 全量重建不叠加。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = _chain_session()

    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")

    second = _run(_mapping_report(), session, team)

    assert second.results[-1].message.startswith("🔗")
    for rule in session["mapped_sub_rules"]:
        threat_entries = [
            entry
            for entry in rule["normalize"]
            if entry.get("index") == "威胁类型"
        ]
        assert len(threat_entries) == 1
        assert len(threat_entries[0]["mappings"]) == 2


def test显式来源覆盖在指令链路成功后记录():
    """主计划含成功的 add_fields(威胁类型, %{B}) → 会话记住来源覆盖。"""
    session = _chain_session()
    step = AddFieldsStep(
        step_id="add-explicit",
        type="add_fields",
        field_name="威胁类型",
        field_value="%{B}",
        value_type="reference",
        rule_group="threat",
        config_ref="session.mapped_sub_rules",
    )
    report = ExecutionReport(
        plan_id="explicit-run",
        results=(
            StepResult(
                step_id="add-explicit",
                operation_type="add_fields",
                status=StepStatus.SUCCESS,
                message="ok",
            ),
        ),
    )

    extended = asyncio.run(
        run_threat_chain_after_mapping(
            report=report,
            plan_steps=(step,),
            session=session,
            team=None,
            progress_sink=None,
        )
    )

    assert session[SESSION_OVERRIDE_KEY] == "B"
    # 无字段映射步骤 → 链路不触发，报告原样
    assert extended.results == report.results


def test会话覆盖优先于相似度判定(monkeypatch):
    """覆盖值存在时直接使用，不再依赖检索得分。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    session = _chain_session()
    session[SESSION_OVERRIDE_KEY] = "src_ip"
    report = _mapping_report()

    extended = _run(report, session, _Team(_ThreatMember(_FULL_MAPPING)))

    summary = extended.results[-1]
    assert "来源字段=src_ip" in summary.message
    for rule in session["mapped_sub_rules"]:
        assert _threat_binding(rule) == "%{src_ip}"


def test非执行决策原样返回():
    """澄清/引导决策不经链路处理。"""
    session = _chain_session()
    decision = {"decision": "clarification"}
    result = asyncio.run(
        run_threat_chain_after_mapping(
            report=decision,
            plan_steps=(),
            session=session,
            team=None,
            progress_sink=None,
        )
    )
    assert result is decision
