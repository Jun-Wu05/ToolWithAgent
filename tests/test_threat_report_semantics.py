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
