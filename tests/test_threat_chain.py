"""#173 威胁类型链路编排集成测试：执行后续跑、失败语义、幂等与会话覆盖。"""

from __future__ import annotations

import asyncio
import base64
import copy
import json

import numpy as np

from agent.core import field_retriever
from application.threat_chain import (
    compile_explicit_threat_plan,
    rank_threat_source_candidates,
    SESSION_OVERRIDE_KEY,
    run_threat_chain_after_mapping,
)
from application.session_state import SessionState
from application.progress import NullProgressSink
from application.request_runtime import run_deterministic_plan
from application.threat_chain_policy import (
    THREAT_FIELD_CHAIN,
    SourceFieldDecision,
    build_threat_chain_steps,
)
from contracts.planner_models import PlanDecision
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


def test自动来源候选复用检索并优先描述字段(monkeypatch):
    """高相似数字类型可先试，但描述型 alarm_name 必须进入三候选。"""
    monkeypatch.setattr(
        "application.threat_chain._retrieve_source_candidates",
        lambda fields: {
            field: [
                (
                    "威胁类型",
                    1.0 if field == "threat_type" else 0.0,
                    "threat_type",
                    "",
                )
            ]
            for field in fields
        },
    )

    ranked = rank_threat_source_candidates(
        ("accuracy", "action", "alarm_name", "event_type1", "threat_type", "src_ip")
    )

    assert ranked == ("threat_type", "alarm_name", "event_type1")


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


def _all_threat_bindings(rule: dict) -> list[str]:
    """按过滤器顺序读取子规则中全部威胁类型绑定。"""
    return [
        value
        for filter_item in rule.get("parser", {}).get("filter", [])
        if isinstance(filter_item, dict)
        and isinstance(filter_item.get("fields"), dict)
        and (value := filter_item["fields"].get("威胁类型")) is not None
    ]


def test自动链路全链成功并追加汇总行(monkeypatch):
    """四步全链：威胁子规则获得 威胁类型=%{attack_type} 绑定与值映射。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    session = _chain_session()
    report = _mapping_report()

    extended = _run(report, session, _Team(_ThreatMember(_FULL_MAPPING)))

    # 主报告映射内容保持不变，标注行用最终配置刷新；末尾追加链路成功步骤 + 🔗 汇总
    assert extended.results[0].artifact.mappings == report.results[0].artifact.mappings
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


def test成功链路用提交后的最终配置刷新事件标注行(monkeypatch):
    """字段映射 artifact 不得继续携带链路前缺少威胁结果的旧行。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    session = _chain_session()
    session["mapped_sub_rules"][0]["normalize"][0]["result"] = ["暴力破解"]
    session["mapped_sub_rules"][1]["normalize"][0]["result"] = ["端口扫描"]

    extended = _run(_mapping_report(), session, _Team(_ThreatMember(_FULL_MAPPING)))

    artifact = extended.results[0].artifact
    assert [row.threat_source_field for row in artifact.event_annotations] == [
        "attack_type",
        "attack_type",
    ]
    assert [row.threat_types for row in artifact.event_annotations] == [
        ("暴力破解",),
        ("端口扫描",),
    ]


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
    annotations = extended.results[0].artifact.event_annotations
    assert [row.threat_types for row in annotations] == [
        ("⚠️ 未生成",),
        ("⚠️ 未生成",),
    ]


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
        assert _all_threat_bindings(rule) == ["%{attack_type}"]
        assert threat_entries[0]["field"] == "threat_type"
        assert threat_entries[0]["entity"] == "威胁"
        assert threat_entries[0]["sim"] is True
        assert threat_entries[0]["core"] is False


def test连续换源后只保留新绑定与完整标准元数据(monkeypatch):
    """从 attack_type 换为 src_ip 后，旧引用消失且生成条目保持规范形态。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = _chain_session()

    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")
    session[SESSION_OVERRIDE_KEY] = "src_ip"

    second = _run(_mapping_report(), session, team)

    assert second.results[-1].message.startswith("🔗")
    for rule in session["mapped_sub_rules"]:
        assert _all_threat_bindings(rule) == ["%{src_ip}"]
        generated = [
            entry
            for entry in rule["normalize"]
            if entry.get("index") == "威胁类型"
        ]
        assert len(generated) == 1
        assert generated[0]["field"] == "threat_type"
        assert generated[0]["entity"] == "威胁"
        assert generated[0]["sim"] is True
        assert generated[0]["core"] is False
    fill_artifact = next(
        result.artifact
        for result in second.results
        if result.step_id == "threat-chain-fill"
    )
    decoded_export = json.loads(
        base64.b64decode(fill_artifact.content).decode("utf-8")
    )
    assert decoded_export == session["mapped_sub_rules"]


def test已有引用链路降级时整体替换为唯一固定值(monkeypatch):
    """来源覆盖不再覆盖威胁子规则时，旧引用不得阻断「其他」降级。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = _chain_session()

    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")
    session[SESSION_OVERRIDE_KEY] = "missing_field"

    degraded = _run(_mapping_report(), session, team)

    assert degraded.results[-1].message.startswith("🔗")
    annotations = degraded.results[0].artifact.event_annotations
    assert [row.threat_source_field for row in annotations] == [
        "—（固定值）",
        "—（固定值）",
    ]
    assert [row.threat_types for row in annotations] == [("其他",), ("其他",)]
    for rule in session["mapped_sub_rules"]:
        assert _all_threat_bindings(rule) == ["其他"]
        generated = [
            entry
            for entry in rule["normalize"]
            if entry.get("index") == "威胁类型"
        ]
        assert len(generated) == 1
        assert generated[0]["field"] == "threat_type"
        assert generated[0]["entity"] == "威胁"
        assert generated[0]["sim"] is True
        assert generated[0]["core"] is False
        assert generated[0]["mappings"] == []


def test换源填充失败时回滚到替换前配置(monkeypatch):
    """删除与添加成功后填充失败，会话不得留下新绑定中间态。"""
    from application.adapters.threat_fill import ThreatFillAdapter

    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = _chain_session()
    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")
    before = copy.deepcopy(session["mapped_sub_rules"])
    session[SESSION_OVERRIDE_KEY] = "src_ip"

    async def _fail_fill(self, step, context, dependencies):
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.FAILED,
            error_code="forced_fill_failure",
            message="测试强制填充失败",
        )

    monkeypatch.setattr(ThreatFillAdapter, "execute", _fail_fill)

    failed = _run(_mapping_report(), session, team)

    assert failed.results[-1].message.startswith("⚠️")
    assert session["mapped_sub_rules"] == before


def test换源威胁类型映射失败时保留替换前配置(monkeypatch):
    """枚举提取成功但威胁类型映射无有效结果时，不触碰旧绑定。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    session = _chain_session()
    first = _run(_mapping_report(), session, _Team(_ThreatMember(_FULL_MAPPING)))
    assert first.results[-1].message.startswith("🔗")
    before = copy.deepcopy(session["mapped_sub_rules"])
    session[SESSION_OVERRIDE_KEY] = "src_ip"

    failed = _run(_mapping_report(), session, _Team(_ThreatMember("[]")))

    assert failed.results[-1].message.startswith("⚠️")
    assert "threat_mapping_empty" in failed.results[-1].message
    assert session["mapped_sub_rules"] == before


def test旧配置多绑定换源只清理威胁链产物(monkeypatch):
    """多 addFields 旧配置换源时，保留来源条目、其他键与非威胁子规则。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = _chain_session()
    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")

    for rule in session["mapped_sub_rules"]:
        rule["parser"]["filter"].extend(
            [
                {
                    "name": "addFields",
                    "id": "",
                    "fields": {"威胁类型": "%{legacy}", "备注": "保留"},
                },
                {"name": "addFields", "id": "", "fields": {"威胁类型": "%{older}"}},
            ]
        )
        rule["normalize"].append(
            {"index": "威胁类型", "field": None, "mappings": [{"old": True}]}
        )
    source_entries_before = [
        copy.deepcopy(
            [
                entry
                for entry in rule["normalize"]
                if entry.get("index") in {"attack_type", "src_ip"}
            ]
        )
        for rule in session["mapped_sub_rules"]
    ]
    non_threat = _threat_rule("普通")
    non_threat["parser"]["filter"][0]["fields"] = {
        "事件名称": "登录事件",
        "事件级别": "信息",
    }
    non_threat_before = copy.deepcopy(non_threat)
    session["mapped_sub_rules"].append(non_threat)
    session[SESSION_OVERRIDE_KEY] = "src_ip"

    replaced = _run(_mapping_report(), session, team)

    assert replaced.results[-1].message.startswith("🔗")
    for index, rule in enumerate(session["mapped_sub_rules"][:2]):
        assert _all_threat_bindings(rule) == ["%{src_ip}"]
        assert source_entries_before[index] == [
            entry
            for entry in rule["normalize"]
            if entry.get("index") in {"attack_type", "src_ip"}
        ]
        assert any(
            filter_item.get("fields") == {"备注": "保留"}
            for filter_item in rule["parser"]["filter"]
        )
        assert all(
            filter_item.get("fields") != {}
            for filter_item in rule["parser"]["filter"]
        )
    assert session["mapped_sub_rules"][2] == non_threat_before


def test结构化会话换源失败同样保持原配置(monkeypatch):
    """Chainlit 实际使用的 SessionState 与字典会话共享原子语义。"""
    from application.adapters.threat_fill import ThreatFillAdapter

    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = SessionState(
        raw_log_lines=[
            "attack_type=暴力破解 src_ip=1.1.1.1",
            "attack_type=端口扫描 src_ip=2.2.2.2",
        ],
        mapped_sub_rules=[_threat_rule("威胁A"), _threat_rule("威胁B")],
    )
    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")
    before = copy.deepcopy(session.mapped_sub_rules)
    session.threat_source_field_override = "src_ip"

    async def _fail_fill(self, step, context, dependencies):
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.FAILED,
            error_code="forced_fill_failure",
            message="测试强制填充失败",
        )

    monkeypatch.setattr(ThreatFillAdapter, "execute", _fail_fill)

    failed = _run(_mapping_report(), session, team)

    assert failed.results[-1].message.startswith("⚠️")
    assert session.mapped_sub_rules == before


def test显式指令全链填充失败时回滚到替换前配置(monkeypatch):
    """Planner/确定性入口提交的威胁全链与自动续跑共享原子语义。"""
    from application.adapters.threat_fill import ThreatFillAdapter

    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = _chain_session()
    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")
    before = copy.deepcopy(session["mapped_sub_rules"])

    explicit = build_threat_chain_steps(
        SourceFieldDecision("src_ip", 1.0, 2, "explicit"),
        config_ref="session.mapped_sub_rules",
        threat_field_state=THREAT_FIELD_CHAIN,
    )
    decision = PlanDecision(
        decision="execute",
        plan_id="explicit-threat-source-switch",
        steps=explicit.steps,
    )

    async def _fail_fill(self, step, context, dependencies):
        return StepResult(
            step_id=step.step_id,
            operation_type=step.type,
            status=StepStatus.FAILED,
            error_code="forced_fill_failure",
            message="测试强制填充失败",
        )

    monkeypatch.setattr(ThreatFillAdapter, "execute", _fail_fill)

    report = asyncio.run(
        run_deterministic_plan(
            session=session,
            team=team,
            plan=decision,
            progress_sink=NullProgressSink(),
        )
    )

    assert report.status == StepStatus.FAILED
    assert session["mapped_sub_rules"] == before
    assert session.get(SESSION_OVERRIDE_KEY) is None


def test显式指令全链成功后一次提交新配置(monkeypatch):
    """显式换源全部步骤成功后，配置与来源覆盖同时可见。"""
    _mock_retrieval(monkeypatch)
    _mock_enum_llm(monkeypatch)
    team = _Team(_ThreatMember(_FULL_MAPPING))
    session = _chain_session()
    first = _run(_mapping_report(), session, team)
    assert first.results[-1].message.startswith("🔗")

    explicit = build_threat_chain_steps(
        SourceFieldDecision("src_ip", 1.0, 2, "explicit"),
        config_ref="session.mapped_sub_rules",
        threat_field_state=THREAT_FIELD_CHAIN,
    )
    report = asyncio.run(
        run_deterministic_plan(
            session=session,
            team=team,
            plan=PlanDecision(
                decision="execute",
                plan_id="explicit-threat-source-switch-success",
                steps=explicit.steps,
            ),
            progress_sink=NullProgressSink(),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert session[SESSION_OVERRIDE_KEY] == "src_ip"
    for rule in session["mapped_sub_rules"]:
        assert _all_threat_bindings(rule) == ["%{src_ip}"]
        for filter_item in rule["parser"]["filter"]:
            if filter_item.get("name") == "removeFields":
                assert "威胁类型" not in filter_item.get("fields", [])


def test显式来源首次建链保持四步且不插入删除():
    session = _chain_session()
    skeleton = build_threat_chain_steps(
        SourceFieldDecision("attack_type", 1.0, 2, "explicit"),
        config_ref="session.mapped_sub_rules",
    )

    compiled = compile_explicit_threat_plan(
        PlanDecision(
            decision="execute",
            plan_id="explicit-first-chain",
            steps=skeleton.steps,
        ),
        session,
    )

    assert [step.type for step in compiled.steps] == [
        "enum_extract",
        "threat_mapping",
        "add_fields",
        "fill",
    ]


def test显式来源已有删除步骤时重新编译但不重复删除():
    session = _chain_session()
    for rule in session["mapped_sub_rules"]:
        rule["normalize"].append({"index": "威胁类型", "mappings": []})
        rule["parser"]["filter"][0]["fields"]["威胁类型"] = "其他"
    skeleton = build_threat_chain_steps(
        SourceFieldDecision("src_ip", 1.0, 2, "explicit"),
        config_ref="session.mapped_sub_rules",
        threat_field_state=THREAT_FIELD_CHAIN,
    )

    compiled = compile_explicit_threat_plan(
        PlanDecision(
            decision="execute",
            plan_id="explicit-already-replace",
            steps=skeleton.steps,
        ),
        session,
    )

    assert [step.type for step in compiled.steps].count("delete_fields") == 1
    assert [step.type for step in compiled.steps] == [
        "enum_extract",
        "threat_mapping",
        "delete_fields",
        "add_fields",
        "fill",
    ]


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
