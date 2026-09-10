"""统一 Planner 公共契约测试。"""

import pytest
from pydantic import ValidationError


def test_session_facts只暴露规划所需事实():
    from application.session_projection import build_session_facts

    session = {
        "api_key": "secret-key",
        "enum_excel_path": r"C:\private\mapping.xlsx",
        "enum_preview": [
            {"目标字段": "event_type3", "原始值": "a", "映射值": "b"},
            {"目标字段": "event_type3", "原始值": "c", "映射值": "d"},
        ],
        "mapped_sub_rules": [
            {"normalize": [{"index": "event_type3", "field": "事件类型"}]}
        ],
        "raw_base64": "sensitive-payload",
    }

    facts = build_session_facts(session)

    assert facts.has_decoded_config is False
    assert facts.has_mapped_sub_rules is True
    assert facts.available_config_refs == ("session.mapped_sub_rules",)
    assert facts.enum_mapping_target_fields == ("event_type3",)
    dumped = facts.model_dump_json()
    assert "secret-key" not in dumped
    assert "private" not in dumped
    assert "sensitive-payload" not in dumped


def test系统元字段不进入字段映射输入():
    """original_log/日志类型 是系统元字段，必须从 available_fields 排除，不送给映射模型（回归 #50）。"""
    from application.session_projection import build_session_facts

    facts = build_session_facts(
        {"decoded_fields": ["original_log", "日志类型", "src_ip", "event_type3"]}
    )

    assert "original_log" not in facts.available_fields
    assert "日志类型" not in facts.available_fields
    assert facts.available_fields == ("src_ip", "event_type3")


def test_fill步骤必须显式声明目标字段和来源():
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "execute",
                "steps": [
                    {
                        "step_id": "s1",
                        "type": "fill",
                        "fill_kind": "enum",
                        "target_fields": [],
                        "source_ref": "session.enum_mapping_table",
                        "config_ref": "session.decoded_config",
                    }
                ],
            }
        )


def test_fill步骤必须显式声明被修改的配置来源():
    """避免适配器在 decoded config 与 mapped sub-rules 之间隐式选择。"""
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "execute",
                "steps": [
                    {
                        "step_id": "s1",
                        "type": "fill",
                        "fill_kind": "enum",
                        "target_fields": ["event_type3"],
                        "source_ref": "session.enum_mapping_table",
                    }
                ],
            }
        )

def test步骤依赖必须引用已出现的步骤():
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "execute",
                "steps": [
                    {
                        "step_id": "s2",
                        "type": "threat_mapping",
                        "source_ref": "step:s1",
                        "depends_on": ["s1"],
                    }
                ],
            }
        )


def test澄清决策不能同时携带执行步骤():
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "clarification",
                "reason_code": "ambiguous_intent",
                "question": "请选择要执行的操作",
                "steps": [{"step_id": "s1", "type": "log_parse"}],
            }
        )

def test执行决策不能没有步骤():
    """执行决策至少需要一个步骤（回归 #42）。"""
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate({"decision": "execute", "plan_id": "p", "steps": []})


def test提案决策携带步骤但不是执行授权():
    from contracts.planner_models import PlanDecision

    decision = PlanDecision.model_validate(
        {
            "decision": "proposal",
            "plan_id": "proposal-1",
            "reason_code": "confirmation_required",
            "question": "将导出当前配置，是否执行？",
            "choices": ["确认执行", "取消"],
            "steps": [
                {
                    "step_id": "export-1",
                    "type": "export",
                    "source_ref": "session.decoded_config",
                }
            ],
        }
    )

    assert decision.decision == "proposal"
    assert decision.steps[0].type == "export"

    with pytest.raises(ValidationError):
        PlanDecision(
            decision="proposal",
            plan_id="empty-proposal",
            reason_code="confirmation_required",
            question="是否执行？",
            choices=("确认执行", "取消"),
        )


@pytest.mark.parametrize("decision", ("confirm", "cancel"))
def test确认与取消只引用待执行计划(decision: str):
    from contracts.planner_models import PlanDecision

    control = PlanDecision(
        decision=decision,
        plan_id=f"{decision}-1",
        pending_plan_id="proposal-1",
    )
    assert control.steps == ()

    with pytest.raises(ValidationError):
        PlanDecision(decision=decision, plan_id=f"{decision}-missing")
    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": decision,
                "plan_id": f"{decision}-steps",
                "pending_plan_id": "proposal-1",
                "steps": [{"step_id": "log-1", "type": "log_parse"}],
            }
        )


def test待确认计划要求固定长度事实摘要():
    from contracts.planner_models import PendingPlan

    pending = PendingPlan.model_validate(
        {
            "plan_id": "proposal-1",
            "session_facts_digest": "a" * 64,
            "steps": [{"step_id": "log-1", "type": "log_parse"}],
        }
    )
    assert pending.plan_id == "proposal-1"

    with pytest.raises(ValidationError):
        PendingPlan.model_validate(
            {
                "plan_id": "proposal-1",
                "session_facts_digest": "short",
                "steps": [{"step_id": "log-1", "type": "log_parse"}],
            }
        )


def test帮助决策必须含guidance_code或answer且不含步骤():
    """guidance 携带 guidance_code 或 answer 之一；不能包含步骤（回归 #42，#149 放宽）。"""
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate({"decision": "guidance"})
    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "guidance",
                "guidance_code": "capabilities",
                "steps": [{"step_id": "s1", "type": "log_parse"}],
            }
        )
    answered = PlanDecision.model_validate(
        {
            "decision": "guidance",
            "answer": "当前子规则事件标注：AUDIT_kv_子规则=审计事件（信息）。",
        }
    )
    assert answered.answer.startswith("当前子规则")
    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "guidance",
                "answer": "回答",
                "steps": [{"step_id": "s1", "type": "log_parse"}],
            }
        )


def test作答字段与执行澄清决策互斥():
    """execute 与 clarification 不得携带 answer，保持三类决策互斥（#149）。"""
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "execute",
                "steps": [
                    {"step_id": "fm-1", "type": "field_mapping", "source_ref": "session.fields"}
                ],
                "answer": "顺带回答",
            }
        )
    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "clarification",
                "reason_code": "missing_facts",
                "question": "请先完成字段映射",
                "answer": "顺带回答",
            }
        )


def test_session_facts投影子规则事件标注事实():
    """各子规则事件名称/级别进入 facts；未标注子规则占位（#149 信息型问答）。"""
    from application.session_projection import build_session_facts

    session = {
        "mapped_sub_rules": [
            {
                "name": "AUDIT_kv_子规则",
                "parser": {
                    "filter": [
                        {"name": "addFields", "id": "", "fields": {"事件名称": "审计事件"}}
                    ]
                },
            },
            {
                "name": "暴力破解_kv_子规则",
                "normalize": [{"index": "事件名称", "result": ["终端告警"]}],
            },
            {"name": "IPS_kv_子规则", "normalize": [{"index": "src_ip", "field": "源IP"}]},
        ]
    }

    facts = build_session_facts(session)

    assert [row.rule_name for row in facts.event_annotations] == [
        "AUDIT_kv_子规则",
        "暴力破解_kv_子规则",
        "IPS_kv_子规则",
    ]
    # filter addFields 与 normalize 两种写入来源都能读出，级别由绑定表确定性推导
    assert facts.event_annotations[0].event_name == "审计事件"
    assert facts.event_annotations[0].event_level == "信息"
    assert facts.event_annotations[1].event_name == "终端告警"
    assert facts.event_annotations[1].event_level == "提醒"
    # 未标注子规则占位，信息型问答才能报出全量名单
    assert facts.event_annotations[2].event_name == ""
    assert facts.event_annotations[2].event_level == ""


def test导出session来源不能声明步骤依赖():
    """session 导出来源不应声明步骤依赖（回归 #42）。"""
    from contracts.planner_models import ExportStep

    with pytest.raises(ValidationError):
        ExportStep.model_validate(
            {
                "step_id": "exp",
                "type": "export",
                "source_ref": "session.mapped_sub_rules",
                "depends_on": ["other"],
            }
        )


def test导出步骤引用必须出现在依赖中():
    """step:<id> 导出来源必须声明在 depends_on 中（回归 #42）。"""
    from contracts.planner_models import ExportStep

    with pytest.raises(ValidationError):
        ExportStep.model_validate(
            {"step_id": "exp", "type": "export", "source_ref": "step:other"}
        )


def test威胁映射来源必须与依赖一致():
    """防止 source_ref 指向未声明步骤，避免绕过本次结果账本。"""
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "execute",
                "steps": [
                    {
                        "step_id": "extract",
                        "type": "enum_extract",
                        "target_field": "event_type3",
                    },
                    {
                        "step_id": "threat",
                        "type": "threat_mapping",
                        "source_ref": "step:extract",
                    },
                ],
            }
        )


def test威胁映射来源禁止引用session旧结果():
    """source_ref 仅允许 user.values 或本次步骤引用，禁止读 session 旧结果（回归 #38）。"""
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "execute",
                "steps": [
                    {
                        "step_id": "threat",
                        "type": "threat_mapping",
                        "source_ref": "session.last_enum_extract_result",
                    }
                ],
            }
        )


def test威胁填充不能读取session旧结果():
    """强制威胁 Fill 引用本次步骤，禁止 last_threat_data 隐式兜底。"""
    from contracts.planner_models import PlanDecision

    with pytest.raises(ValidationError):
        PlanDecision.model_validate(
            {
                "decision": "execute",
                "steps": [
                    {
                        "step_id": "fill",
                        "type": "fill",
                        "fill_kind": "threat",
                        "target_fields": ["event_type3"],
                        "source_ref": "session.last_threat_data",
                        "config_ref": "session.mapped_sub_rules",
                    }
                ],
            }
        )

def test步骤结果拒绝未知或无约束产物():
    """防止执行接缝重新接受 artifact_type 加任意 payload 的旧协议。"""
    from contracts.planner_models import StepResult

    with pytest.raises(ValidationError):
        StepResult.model_validate(
            {
                "step_id": "extract",
                "operation_type": "enum_extract",
                "status": "success",
                "artifact": {
                    "artifact_type": "unknown",
                    "payload": {"任意": "数据"},
                    "item_count": 1,
                },
            }
        )

def test_session_facts集中汇总日志分类字段(monkeypatch):
    """证明 Planner 和执行器共享同一字段事实，不在各层重复解释日志状态。"""
    import application.field_source as field_source
    from application.session_projection import build_session_facts

    monkeypatch.setattr(
        field_source,
        "extract_log_fields_for_mapping",
        lambda classification, raw_log_lines: ["src_ip", "event_type3"],
    )

    facts = build_session_facts(
        {
            "log_classification": {"类型A": {}},
            "raw_log_lines": ["src_ip=1.1.1.1 event_type3=attack"],
        }
    )

    assert facts.available_fields == ("src_ip", "event_type3")


def test有日志字段时Excel列头不进入字段映射输入(monkeypatch):
    """有真实日志字段时，Excel 列头（decoded_fields）不得混入映射候选（回归 #78）。"""
    import application.field_source as field_source
    from application.session_projection import build_session_facts

    monkeypatch.setattr(
        field_source,
        "extract_log_fields_for_mapping",
        lambda classification, raw_log_lines: ["alarm_name", "src_ip"],
    )

    facts = build_session_facts(
        {
            "decoded_fields": ["发生时间", "事件名称", "设备"],
            "log_classification": {"AUDIT": {}},
            "raw_log_lines": ['alarm_name="attack" src_ip=1.1.1.1'],
        }
    )

    assert facts.available_fields == ("alarm_name", "src_ip")


def test无日志字段时回退使用配置字段():
    """Base64/TXT 配置上传场景没有日志字段，decoded_fields 仍参与映射。"""
    from application.session_projection import build_session_facts

    facts = build_session_facts({"decoded_fields": ["event_type3", "src_ip"]})

    assert facts.available_fields == ("event_type3", "src_ip")


def test对话历史必须符合受限类型契约():
    """阻止任意 session 字典或额外敏感字段跨过 Planner 接缝。"""
    from contracts.planner_models import ConversationTurn

    with pytest.raises(ValidationError):
        ConversationTurn.model_validate(
            {
                "role": "user",
                "content": "执行字段映射",
                "api_key": "不应进入 Planner",
            }
        )


def _execute_payload():
    return {
        "decision": "execute",
        "steps": [
            {"step_id": "fm-1", "type": "field_mapping", "source_ref": "session.fields"}
        ],
    }


def test_coerce接受字典输出():
    from agent.core.planner import _coerce_plan_decision

    decision = _coerce_plan_decision(_execute_payload())
    assert decision.decision == "execute"
    assert decision.steps[0].type == "field_mapping"


def test_coerce接受裸JSON字符串():
    """Agno 解析失败时常保留 content 为原始字符串，必须能从中还原计划。"""
    import json

    from agent.core.planner import _coerce_plan_decision

    decision = _coerce_plan_decision(json.dumps(_execute_payload(), ensure_ascii=False))
    assert decision.decision == "execute"


def test_coerce接受带围栏和解释文本的JSON字符串():
    import json

    from agent.core.planner import _coerce_plan_decision

    fenced = "这是计划：\n```json\n" + json.dumps(_execute_payload(), ensure_ascii=False) + "\n```\n已完成。"
    decision = _coerce_plan_decision(fenced)
    assert decision.decision == "execute"


def test_coerce剥离顶层多余字段后仍校验():
    """模型自添 explanation 等顶层多余键时兜底剥离，步骤结构仍严格。"""
    from agent.core.planner import _coerce_plan_decision

    payload = _execute_payload()
    payload["explanation"] = "我决定执行字段映射"
    decision = _coerce_plan_decision(payload)
    assert decision.decision == "execute"


def test_coerce不会掩盖语义错误():
    """剥离多余键只在存在多余键时生效；clarification 缺 reason_code 仍必须失败。"""
    from agent.core.planner import _coerce_plan_decision

    with pytest.raises(ValidationError):
        _coerce_plan_decision({"decision": "clarification", "question": "缺少原因"})


def test_coerce拒绝非法JSON字符串():
    from agent.core.planner import _coerce_plan_decision

    with pytest.raises(ValueError):
        _coerce_plan_decision("这不是一段 JSON")


def test_coerce拒绝不支持类型():
    from agent.core.planner import _coerce_plan_decision

    with pytest.raises(TypeError):
        _coerce_plan_decision(42)


def test_coerce透传已解析的PlanDecision():
    from agent.core.planner import _coerce_plan_decision
    from contracts.planner_models import PlanDecision

    original = PlanDecision.model_validate(_execute_payload())
    assert _coerce_plan_decision(original) is original


def test事件标注行携带威胁来源与有序最终类型():
    """报告契约扩展不得破坏旧构造，并保留每条规则实际命中值的顺序。"""
    from contracts.planner_models import EventAnnotationRow

    legacy = EventAnnotationRow(rule_name="普通规则", event_name="登录事件")
    assert legacy.threat_source_field == ""
    assert legacy.threat_types == ()

    enriched = EventAnnotationRow(
        rule_name="威胁规则",
        event_name="网络攻击",
        event_level="提醒",
        threat_source_field="attack_type",
        threat_types=("暴力破解", "端口扫描"),
    )
    assert enriched.threat_source_field == "attack_type"
    assert enriched.threat_types == ("暴力破解", "端口扫描")
