"""#210 最终威胁配置到事件标注报告行的纯策略测试。"""

from application.threat_report import build_threat_report_rows
from contracts.planner_models import EventAnnotationRow


def _rule(name: str, sample_values: list[str]) -> dict:
    return {
        "name": name,
        "normalize": [
            {"index": "attack_type", "result": sample_values},
            {
                "index": "威胁类型",
                "mappings": [
                    {
                        "mappingType": "REGULAR",
                        "orgValue": r"(?i).*brute.*",
                        "mappingValue": "暴力破解",
                    },
                    {
                        "mappingType": "EQUAL",
                        "orgValue": "scan",
                        "mappingValue": "端口扫描",
                    },
                ],
            },
        ],
        "parser": {
            "filter": [
                {
                    "name": "addFields",
                    "fields": {"事件名称": "网络攻击", "威胁类型": "%{attack_type}"},
                }
            ]
        },
    }


def test每条威胁规则只展示自身样例实际命中的最终类型():
    annotations = (
        EventAnnotationRow(rule_name="brute-rule", event_name="网络攻击", event_level="提醒"),
        EventAnnotationRow(rule_name="scan-rule", event_name="网络攻击", event_level="提醒"),
    )

    rows = build_threat_report_rows(
        annotations,
        [_rule("brute-rule", ["BRUTE login"]), _rule("scan-rule", ["scan"])],
        chain_succeeded=True,
    )

    assert rows[0].threat_source_field == "attack_type"
    assert rows[0].threat_types == ("暴力破解",)
    assert rows[1].threat_source_field == "attack_type"
    assert rows[1].threat_types == ("端口扫描",)


def test同一规则多个样例按出现顺序去重最终类型():
    annotation = EventAnnotationRow(
        rule_name="mixed-rule", event_name="网络攻击", event_level="提醒"
    )

    row = build_threat_report_rows(
        (annotation,),
        [_rule("mixed-rule", ["BRUTE login", "scan", "BRUTE login"])],
        chain_succeeded=True,
    )[0]

    assert row.threat_types == ("暴力破解", "端口扫描")


def test固定值降级普通事件和未知状态使用约定占位():
    fixed_rule = _rule("fixed-rule", [])
    fixed_rule["parser"]["filter"][0]["fields"]["威胁类型"] = "其他"
    annotations = (
        EventAnnotationRow(rule_name="fixed-rule", event_name="其他告警", event_level="提醒"),
        EventAnnotationRow(rule_name="normal-rule", event_name="登录事件", event_level="信息"),
        EventAnnotationRow(rule_name="unknown-rule", status="uncertain"),
    )

    fixed, normal, unknown = build_threat_report_rows(
        annotations, [fixed_rule], chain_succeeded=True
    )

    assert (fixed.threat_source_field, fixed.threat_types) == ("—（固定值）", ("其他",))
    assert (normal.threat_source_field, normal.threat_types) == ("", ())
    assert unknown.threat_types == ("⚠️ 未生成",)


def test已知来源但样例缺失或无法匹配时不猜测():
    missing_sample = _rule("missing-sample", [])
    invalid_pattern = _rule("invalid-pattern", ["BRUTE login"])
    invalid_pattern["normalize"][1]["mappings"] = [
        {"mappingType": "REGULAR", "orgValue": "[", "mappingValue": "不应命中"}
    ]
    annotations = tuple(
        EventAnnotationRow(rule_name=name, event_name="网络攻击", event_level="提醒")
        for name in ("missing-sample", "invalid-pattern")
    )

    rows = build_threat_report_rows(
        annotations, [missing_sample, invalid_pattern], chain_succeeded=True
    )

    assert [row.threat_source_field for row in rows] == ["attack_type", "attack_type"]
    assert [row.threat_types for row in rows] == [
        ("⚠️ 无法从样例判定",),
        ("⚠️ 无法从样例判定",),
    ]


def test链路失败时威胁行明确显示未生成():
    annotation = EventAnnotationRow(
        rule_name="brute-rule", event_name="网络攻击", event_level="提醒"
    )

    row = build_threat_report_rows(
        (annotation,), [_rule("brute-rule", ["BRUTE login"])], chain_succeeded=False
    )[0]

    assert row.threat_source_field == ""
    assert row.threat_types == ("⚠️ 未生成",)
