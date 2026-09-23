"""#173 威胁类型链路纯策略测试：触发判定、X 判定、链路构造与值全覆盖校验。"""

from __future__ import annotations

from contracts.planner_models import (
    EventAnnotationRow,
    FieldMappingArtifact,
    FieldMappingRow,
    StepResult,
    StepStatus,
)
from application.threat_chain_policy import (
    THREAT_FIELD_ABSENT,
    THREAT_FIELD_CHAIN,
    THREAT_FIELD_EXISTING,
    SourceFieldDecision,
    build_threat_chain_steps,
    collect_threat_field_pools,
    degraded_mapping_ratio,
    determine_source_field,
    evaluate_chain_trigger,
    inspect_threat_field_state,
    is_code_only_value,
    is_safe_rederive_plan,
    should_rederive,
    validate_threat_mapping_coverage,
)
from agent.shared.event_classify import THREAT_TYPE_FIELD


def _mapping_result(annotations) -> StepResult:
    """构造带事件标注的成功字段映射结果行。"""
    return StepResult(
        step_id="mapping",
        operation_type="field_mapping",
        status=StepStatus.SUCCESS,
        artifact=FieldMappingArtifact(
            item_count=1,
            mappings=(
                FieldMappingRow(
                    **{
                        "原始字段名": "a",
                        "系统属性名称": "源地址",
                        "匹配状态": "匹配成功",
                    }
                ),
            ),
            event_annotations=tuple(annotations),
        ),
        message="ok",
    )


def _annotation(rule_name, event_name="网络攻击", status="judged"):
    return EventAnnotationRow(
        rule_name=rule_name, event_name=event_name, status=status
    )


# ---------------------------------------------------------------------------
# S0 触发判定
# ---------------------------------------------------------------------------


def test触发判定识别威胁子规则并排除待确认():
    trigger = evaluate_chain_trigger(
        [
            _mapping_result(
                [
                    _annotation("威胁A"),
                    _annotation("普通B", event_name="正常通信"),
                    _annotation("待确认C", status="uncertain"),
                ]
            )
        ]
    )
    assert trigger.should_run
    assert trigger.threat_rule_names == ("威胁A",)
    assert trigger.uncertain_rule_names == ("待确认C",)


def test触发判定全部待确认时只提示不跑():
    trigger = evaluate_chain_trigger(
        [_mapping_result([_annotation("x", status="uncertain")])]
    )
    assert not trigger.should_run
    assert trigger.hint_only


def test触发判定无字段映射产物时返回None():
    assert evaluate_chain_trigger([]) is None
    failed = StepResult(
        step_id="mapping",
        operation_type="field_mapping",
        status=StepStatus.FAILED,
        error_code="x",
        message="failed",
    )
    assert evaluate_chain_trigger([failed]) is None


# ---------------------------------------------------------------------------
# 字段池
# ---------------------------------------------------------------------------


def _threat_rule(name, indexes):
    return {
        "name": name,
        "normalize": [
            {"index": idx, "mappings": []} for idx in indexes
        ],
    }


def test字段池收集剔除元字段():
    pools = collect_threat_field_pools(
        [
            _threat_rule("威胁A", ["original_log", "日志类型", "attack_type", "src_ip"]),
            _threat_rule("普通B", ["attack_type"]),
        ],
        ("威胁A", "普通B不在名单"),
    )
    assert pools == {"威胁A": ("attack_type", "src_ip")}


# ---------------------------------------------------------------------------
# S1 X 判定
# ---------------------------------------------------------------------------


POOLS = {"威胁A": ("attack_type", "src_ip"), "威胁B": ("attack_type", "dst_port")}


def _table(**field_rows):
    return {name: [tuple(row) for row in rows] for name, rows in field_rows.items()}


def testX判定取相似度最高且覆盖全部威胁子规则():
    table = _table(
        attack_type=[(THREAT_TYPE_FIELD, 0.82, "threat_type", "")],
        src_ip=[(THREAT_TYPE_FIELD, 0.30, "threat_type", "")],
    )
    decision = determine_source_field(POOLS, table)
    assert decision.source_field == "attack_type"
    assert decision.score == 0.82
    assert decision.covered_rules == 2
    assert decision.reason == "similarity"


def testX判定覆盖不足的字段不参与():
    table = _table(src_ip=[(THREAT_TYPE_FIELD, 0.95, "threat_type", "")])
    decision = determine_source_field(POOLS, table)
    assert decision.source_field is None
    assert decision.reason == "degrade_below_threshold"


def testX判定无覆盖字段时降级():
    decision = determine_source_field(
        {"威胁A": ("a",), "威胁B": ("b",)}, _table(a=[(THREAT_TYPE_FIELD, 0.9, "t", "")])
    )
    assert decision.source_field is None
    assert decision.reason == "degrade_no_coverage"


def testX判定低于阈值降级():
    table = _table(attack_type=[(THREAT_TYPE_FIELD, 0.42, "threat_type", "")])
    assert determine_source_field(POOLS, table).reason == "degrade_below_threshold"


def testX判定会话覆盖优先且不走相似度():
    decision = determine_source_field(
        POOLS, {}, override="attack_type"
    )
    assert decision.source_field == "attack_type"
    assert decision.reason == "session_override"


def testX判定覆盖不足的会话覆盖值判为无效():
    decision = determine_source_field(POOLS, {}, override="src_ip")
    assert decision.source_field is None
    assert decision.reason == "override_not_covering"


# ---------------------------------------------------------------------------
# 威胁字段现状探测
# ---------------------------------------------------------------------------


def test现状探测三种状态():
    absent = [_threat_rule("威胁A", ["attack_type"])]
    assert inspect_threat_field_state(absent, ("威胁A",)) == THREAT_FIELD_ABSENT

    existing = [
        {
            "name": "威胁A",
            "normalize": [{"index": "attack_type"}, {"index": THREAT_TYPE_FIELD}],
        }
    ]
    assert inspect_threat_field_state(existing, ("威胁A",)) == THREAT_FIELD_EXISTING

    chain = [
        {
            "name": "威胁A",
            "normalize": [{"index": THREAT_TYPE_FIELD}],
            "parser": {
                "filter": [
                    {"name": "addFields", "id": "", "fields": {THREAT_TYPE_FIELD: "%{attack_type}"}}
                ]
            },
        }
    ]
    assert inspect_threat_field_state(chain, ("威胁A",)) == THREAT_FIELD_CHAIN


# ---------------------------------------------------------------------------
# 链路构造器
# ---------------------------------------------------------------------------


def _chosen(field="attack_type", score=0.82):
    from application.threat_chain_policy import SourceFieldDecision

    return SourceFieldDecision(field, score, 2, "similarity")


def test构造器四步全链():
    plan = build_threat_chain_steps(_chosen(), config_ref="session.mapped_sub_rules")
    assert [step.type for step in plan.steps] == [
        "enum_extract",
        "threat_mapping",
        "add_fields",
        "fill",
    ]
    add = plan.steps[2]
    assert add.field_name == THREAT_TYPE_FIELD
    assert add.field_value == "%{attack_type}"
    assert add.value_type == "reference"
    assert add.rule_group == "threat"
    fill = plan.steps[3]
    assert fill.fill_kind == "threat"
    assert fill.target_fields == (THREAT_TYPE_FIELD,)
    assert fill.source_ref == "step:threat-chain-map"
    assert not plan.degraded


def test构造器链路自产时先删后加整体替换():
    plan = build_threat_chain_steps(
        _chosen(),
        config_ref="session.mapped_sub_rules",
        threat_field_state=THREAT_FIELD_CHAIN,
    )
    assert [step.type for step in plan.steps] == [
        "enum_extract",
        "threat_mapping",
        "delete_fields",
        "add_fields",
        "fill",
    ]
    delete = plan.steps[2]
    assert delete.fields == (THREAT_TYPE_FIELD,)
    assert delete.rule_group == "threat"


def test构造器存量条目跳过加字段():
    plan = build_threat_chain_steps(
        _chosen(),
        config_ref="session.mapped_sub_rules",
        threat_field_state=THREAT_FIELD_EXISTING,
    )
    assert [step.type for step in plan.steps] == [
        "enum_extract",
        "threat_mapping",
        "fill",
    ]
    assert "跳过加字段" in plan.skipped_add_reason


def test构造器降级单步固定值其他():
    from application.threat_chain_policy import SourceFieldDecision

    degraded = SourceFieldDecision(None, 0.0, 0, "degrade_below_threshold")
    plan = build_threat_chain_steps(degraded, config_ref="session.mapped_sub_rules")
    assert plan.degraded
    assert len(plan.steps) == 1
    add = plan.steps[0]
    assert add.field_value == "其他"
    assert add.value_type == "fixed"


# ---------------------------------------------------------------------------
# 统一来源覆盖校验（#277）
# ---------------------------------------------------------------------------

_COVERAGE_TARGETS = {"暴力破解", "端口扫描", "信息泄露", "其他"}


def test覆盖校验完整结果通过():
    rows = [
        {"mappingType": "EQUAL", "orgValue": "brute", "mappingValue": "暴力破解"},
        {"mappingType": "REGULAR", "orgValue": "(?i).*scan.*", "mappingValue": "端口扫描"},
    ]
    assert (
        validate_threat_mapping_coverage(
            ["brute", "slow scan"], rows, _COVERAGE_TARGETS
        )
        is None
    )


def test覆盖校验合法分组正则覆盖多个输入():
    rows = [
        {"mappingType": "REGULAR", "orgValue": "(?:暴力破解|撞库)", "mappingValue": "暴力破解"},
    ]
    assert (
        validate_threat_mapping_coverage(["暴力破解", "撞库"], rows, _COVERAGE_TARGETS)
        is None
    )


def test覆盖校验缺项拒绝():
    rows = [{"mappingType": "EQUAL", "orgValue": "brute", "mappingValue": "暴力破解"}]
    violation = validate_threat_mapping_coverage(
        ["brute", "phish"], rows, _COVERAGE_TARGETS
    )
    assert violation == "declared_input_uncovered"


def test覆盖校验来源外结果拒绝():
    rows = [
        {"mappingType": "EQUAL", "orgValue": "brute", "mappingValue": "暴力破解"},
        {"mappingType": "EQUAL", "orgValue": "unknown", "mappingValue": "端口扫描"},
    ]
    violation = validate_threat_mapping_coverage(["brute"], rows, _COVERAGE_TARGETS)
    assert violation == "row_out_of_source"


def test覆盖校验正则重叠多行命中同一输入拒绝():
    rows = [
        {"mappingType": "EQUAL", "orgValue": "brute", "mappingValue": "暴力破解"},
        {"mappingType": "REGULAR", "orgValue": "(?i).*brute.*", "mappingValue": "端口扫描"},
    ]
    violation = validate_threat_mapping_coverage(["brute"], rows, _COVERAGE_TARGETS)
    assert violation == "declared_input_multi_matched"


def test覆盖校验重复结果拒绝():
    row = {"mappingType": "EQUAL", "orgValue": "brute", "mappingValue": "暴力破解"}
    violation = validate_threat_mapping_coverage(
        ["brute"], [dict(row), dict(row)], _COVERAGE_TARGETS
    )
    assert violation == "declared_input_multi_matched"


def test覆盖校验枚举外映射值拒绝():
    rows = [{"mappingType": "EQUAL", "orgValue": "brute", "mappingValue": "不存在类型"}]
    violation = validate_threat_mapping_coverage(["brute"], rows, _COVERAGE_TARGETS)
    assert violation == "mapping_value_out_of_enum"


def test覆盖校验返回值不含真实输入或映射值():
    rows = [
        {"mappingType": "EQUAL", "orgValue": "真实输入甲", "mappingValue": "不存在类型乙"},
    ]
    violation = validate_threat_mapping_coverage(["真实输入甲"], rows, _COVERAGE_TARGETS)
    assert violation == "mapping_value_out_of_enum"
    assert "真实输入甲" not in violation
    assert "不存在类型乙" not in violation


# ---------------------------------------------------------------------------
# 无语义数字代码判定（#277）
# ---------------------------------------------------------------------------


def test数字代码判定纯数字与常见代码分隔符():
    for value in ["30", "10", "30-10", "30_10", "30.10", "30:10", "30/10", " 30 10 "]:
        assert is_code_only_value(value), value


def test数字代码判定含字母或文字即非代码():
    for value in ["", "30a", "攻击30", "信息", "attack", "30级"]:
        assert not is_code_only_value(value), value


# ---------------------------------------------------------------------------
# 自恢复③（#225）：结果全落「其他」时的确定性改选
# ---------------------------------------------------------------------------


def test改选判定全落其他时触发():
    assert should_rederive(["其他", "其他"], source_reason="similarity")


def test改选判定有任一非其他时不触发():
    assert not should_rederive(["其他", "暴力破解"], source_reason="similarity")


def test改选判定空映射不触发():
    assert not should_rederive([], source_reason="similarity")


def test改选判定用户指定或会话纠正的来源不触发():
    assert not should_rederive(["其他", "其他"], source_reason="explicit")
    assert not should_rederive(["其他", "其他"], source_reason="session_override")


def test降级占比把空值与其他同等计入():
    assert degraded_mapping_ratio(["其他", "", "暴力破解"]) == 2 / 3
    assert degraded_mapping_ratio([]) == 0.0


def testX判定排除已试字段后取下一覆盖候选():
    pools = {"威胁A": ("attack_type", "src_ip"), "威胁B": ("attack_type", "src_ip")}
    table = _table(
        attack_type=[(THREAT_TYPE_FIELD, 0.82, "threat_type", "")],
        src_ip=[(THREAT_TYPE_FIELD, 0.60, "threat_type", "")],
    )
    decision = determine_source_field(pools, table, exclude=("attack_type",))
    assert decision.source_field == "src_ip"
    assert decision.reason == "similarity"


def testX判定排除后无覆盖候选时返回None():
    table = _table(attack_type=[(THREAT_TYPE_FIELD, 0.82, "threat_type", "")])
    decision = determine_source_field(POOLS, table, exclude=("attack_type",))
    assert decision.source_field is None
    assert decision.reason == "degrade_no_coverage"


def test改选门禁接受先删后加链路四步():
    plan = build_threat_chain_steps(
        SourceFieldDecision("src_ip", 0.6, 2, "similarity"),
        config_ref="session.mapped_sub_rules",
        threat_field_state=THREAT_FIELD_CHAIN,
    )
    assert is_safe_rederive_plan(plan.steps)


def test改选门禁拒绝触碰威胁类型以外的目标():
    from contracts.planner_models import DeleteFieldsStep

    foreign_delete = DeleteFieldsStep(
        step_id="d",
        type="delete_fields",
        fields=("备注",),
        rule_group="threat",
        config_ref="session.mapped_sub_rules",
    )
    assert not is_safe_rederive_plan((foreign_delete,))
