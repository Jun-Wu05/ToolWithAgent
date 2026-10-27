"""Operational events have no threat determination (#416)."""
import pytest
from application.threat_report import build_threat_report_rows
from contracts.planner_models import EventAnnotationRow


@pytest.mark.parametrize("event_name", ["审计事件", "登录事件", "进程操作", "dns查询"])
@pytest.mark.parametrize("chain_succeeded", [False, True])
def test_information_event_threat_fields_are_not_applicable(event_name, chain_succeeded):
    rows = build_threat_report_rows((EventAnnotationRow(
        rule_name="audit", event_name=event_name, event_level="信息", status="judged",
    ),), [], chain_succeeded=chain_succeeded)
    assert rows[0].threat_source_field == "不适用"
    assert rows[0].threat_types == ("不适用",)


def test_mixed_event_report_preserves_threat_and_uncertain_semantics():
    annotations = (
        EventAnnotationRow(rule_name="audit", event_name="审计事件", event_level="信息"),
        EventAnnotationRow(rule_name="threat", event_name="网络攻击", event_level="提醒"),
        EventAnnotationRow(rule_name="unknown", status="uncertain"),
    )
    rows = build_threat_report_rows(annotations, [], chain_succeeded=False)
    assert rows[0].threat_types == ("不适用",)
    assert rows[1].threat_types == ("⚠️ 未生成",)
    assert rows[2].threat_types == ("⚠️ 未生成",)
    assert rows[1].threat_source_field != "不适用"
    assert rows[2].threat_source_field != "不适用"


def operation_rule(binding, samples=(), mappings=()):
    return {"name": "audit", "parser": {"filter": [{"name": "addFields", "fields": {"操作类型": binding}}]},
            "normalize": [{"index": "action", "result": list(samples)},
                          {"index": "操作类型", "mappings": list(mappings)}]}


@pytest.mark.parametrize("binding,samples,mappings,source,values", [
    ("数据库审计", (), (), "—（固定值）", ("数据库审计",)),
    ("", (), (), "", ("⚠️ 未生成",)),
    ("%{action}", ("in", "out", "in"), (
        {"mappingType": "EQUAL", "orgValue": "in", "mappingValue": "登录"},
        {"mappingType": "EQUAL", "orgValue": "out", "mappingValue": "登出"},
    ), "action", ("登录", "登出")),
    ("%{action}", (), (), "action", ("⚠️ 无法从样例判定",)),
    ("%{action}", ("登录", "登出"), (), "action", ("登录", "登出")),
])
def test_common_type_result_uses_actual_operation_binding(binding, samples, mappings, source, values):
    from application.threat_report import event_type_determination
    row = EventAnnotationRow(rule_name="audit", event_name="审计事件", event_level="信息")
    assert event_type_determination(row, [operation_rule(binding, samples, mappings)]) == (source, values)


def test_common_type_result_does_not_infer_binding_or_overwrite_failed_threat():
    from application.threat_report import event_type_determination
    row = EventAnnotationRow(rule_name="audit", event_name="审计事件", event_level="信息")
    assert event_type_determination(row, [{"name": "audit", "normalize": [{"index": "action", "result": ["登录"]}]}]) == ("", ("⚠️ 未生成",))
    threat = EventAnnotationRow(rule_name="audit", event_name="网络攻击", event_level="提醒", threat_types=("⚠️ 未生成",))
    assert event_type_determination(threat, [operation_rule("数据库审计")]) == ("", ("⚠️ 未生成",))
