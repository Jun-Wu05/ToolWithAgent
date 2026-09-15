"""统一 PlanExecutor 的依赖、停止和结果验证测试。"""

import asyncio

from application.execution import ExecutionContext
from application.execution_policy import create_plan_executor
from contracts.planner_models import (
    EnumValuesArtifact,
    PlanDecision,
    StepResult,
    StepStatus,
    ThreatMappingArtifact,
)
from contracts.session_facts import SessionFacts


class RecordingAdapter:
    """记录调用并返回预设结果的测试适配器。"""

    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    async def execute(self, step, context, dependencies):
        """保存类型化入参，证明执行器没有传递任意步骤字典。"""
        self.calls.append((step, dependencies))
        return next(self.results)


def _execute(decision, adapters, facts=None):
    """用独立事件循环运行执行器，避免测试依赖额外 pytest 插件。"""
    return asyncio.run(
        create_plan_executor(adapters).execute(
            decision,
            ExecutionContext(session={}, session_facts=facts or SessionFacts()),
        )
    )


KV_SESSION = {
    "raw_log_lines": ["category=attack src=10.0.0.1", "category=scan src=10.0.0.2"]
}
JSON_SESSION = {
    "raw_log_lines": [
        '{"detail":{"event_type":"attack"},"src":"10.0.0.1"}',
        '{"detail":{"event_type":"scan"},"src":"10.0.0.2"}',
    ]
}


def _log_parse_decision(feature_field=None):
    """构造带或不带显式分类特征字段的 log_parse 决策。"""
    step = {"step_id": "log-1", "type": "log_parse"}
    if feature_field is not None:
        step["feature_field"] = feature_field
    return PlanDecision.model_validate(
        {"decision": "execute", "plan_id": "plan-log", "steps": [step]}
    )


def _success_log_result():
    return StepResult(
        step_id="log-1",
        operation_type="log_parse",
        status=StepStatus.SUCCESS,
    )


def _execute_with_session(decision, adapters, session, facts=None):
    return asyncio.run(
        create_plan_executor(adapters).execute(
            decision,
            ExecutionContext(
                session=session, session_facts=facts or SessionFacts(has_logs=True)
            ),
        )
    )


def test显式分类特征字段不存在时执行前拦截():
    """键不在日志体键集合时 NEEDS_INPUT，文案列出可用键，不进入适配器。"""
    adapter = RecordingAdapter([_success_log_result()])

    report = _execute_with_session(
        _log_parse_decision("ghost_field"), {"log_parse": adapter}, KV_SESSION
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "feature_field_not_found"
    assert adapter.calls == []
    message = report.results[0].message or ""
    assert "ghost_field" in message
    assert "可用的字段" in message
    assert "category" in message
    assert "src" in message


def test显式分类特征字段不存在时保留旧分类结果():
    """NEEDS_INPUT 不改变会话中已有分类结果。"""
    session = dict(KV_SESSION)
    session["log_classification"] = {"旧类型": {"feature": "old"}}
    adapter = RecordingAdapter([_success_log_result()])

    report = _execute_with_session(
        _log_parse_decision("ghost_field"), {"log_parse": adapter}, session
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert session["log_classification"] == {"旧类型": {"feature": "old"}}


def test显式分类特征字段大小写不敏感唯一匹配时规范化执行():
    """追问后单字回复「Category」不再被拦截：唯一大小写匹配规范化为 category（#122）。"""
    adapter = RecordingAdapter([_success_log_result()])

    report = _execute_with_session(
        _log_parse_decision("Category"), {"log_parse": adapter}, KV_SESSION
    )

    assert report.status == StepStatus.SUCCESS
    assert len(adapter.calls) == 1
    # 传给适配器的是规范化后的真实键名
    assert adapter.calls[0][0].feature_field == "category"


def test显式分类特征字段大小写歧义时仍拦截():
    """存在多个仅大小写不同的键时不得代用户选择，停下追问并列明歧义。"""
    session = {
        "raw_log_lines": ["Category=a src=1.1.1.1", "CATEGORY=b src=2.2.2.2"]
    }
    adapter = RecordingAdapter([_success_log_result()])

    report = _execute_with_session(
        _log_parse_decision("category"), {"log_parse": adapter}, session
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "feature_field_not_found"
    message = report.results[0].message or ""
    assert "仅大小写不同" in message
    assert adapter.calls == []


def test显式分类特征字段存在时放行执行():
    """键精确命中（KV 键名）时校验通过并调用适配器。"""
    adapter = RecordingAdapter([_success_log_result()])

    report = _execute_with_session(
        _log_parse_decision("category"), {"log_parse": adapter}, KV_SESSION
    )

    assert report.status == StepStatus.SUCCESS
    assert len(adapter.calls) == 1


def test键校验支持JSON点分路径():
    """JSON 嵌套字段以点分路径进入键集合，显式路径键可精确命中。"""
    adapter = RecordingAdapter([_success_log_result()])

    report = _execute_with_session(
        _log_parse_decision("detail.event_type"), {"log_parse": adapter}, JSON_SESSION
    )

    assert report.status == StepStatus.SUCCESS
    assert len(adapter.calls) == 1


def test不带feature_field时不做键校验():
    """裸 log_parse 只受日志存在校验约束，不因键集合而拦截。"""
    adapter = RecordingAdapter([_success_log_result()])

    report = _execute_with_session(_log_parse_decision(), {"log_parse": adapter}, KV_SESSION)

    assert report.status == StepStatus.SUCCESS
    assert len(adapter.calls) == 1


def test步骤失败后立即停止且不调用后续适配器():
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-stop",
            "steps": [
                {"step_id": "extract", "type": "enum_extract", "target_field": "event_type3"},
                {
                    "step_id": "threat",
                    "type": "threat_mapping",
                    "source_ref": "step:extract",
                    "depends_on": ["extract"],
                },
            ],
        }
    )
    extract_adapter = RecordingAdapter(
        [
            StepResult(
                step_id="extract",
                operation_type="enum_extract",
                status=StepStatus.FAILED,
                error_code="enum_extract_failed",
            )
        ]
    )
    threat_adapter = RecordingAdapter([])

    report = _execute(
        decision,
        {"enum_extract": extract_adapter, "threat_mapping": threat_adapter},
        SessionFacts(has_logs=True, available_fields=("event_type3",)),
    )

    assert report.status == StepStatus.FAILED
    assert len(report.results) == 1
    assert threat_adapter.calls == []


def test三步计划只消费本次显式依赖的产物():
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-three",
            "steps": [
                {"step_id": "extract", "type": "enum_extract", "target_field": "event_type3"},
                {
                    "step_id": "threat",
                    "type": "threat_mapping",
                    "source_ref": "step:extract",
                    "depends_on": ["extract"],
                },
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "threat",
                    "target_fields": ["event_type3"],
                    "source_ref": "step:threat",
                    "config_ref": "session.mapped_sub_rules",
                    "depends_on": ["threat"],
                },
            ],
        }
    )
    enum_artifact = EnumValuesArtifact(values=("a", "b"), item_count=2)
    threat_artifact = ThreatMappingArtifact(
        mappings=(
            {
                "mappingType": "EQUAL",
                "orgValue": "a",
                "mappingValue": "x",
            },
        ),
        item_count=1,
    )
    extract_adapter = RecordingAdapter(
        [StepResult(step_id="extract", operation_type="enum_extract", status="success", artifact=enum_artifact)]
    )
    threat_adapter = RecordingAdapter(
        [StepResult(step_id="threat", operation_type="threat_mapping", status="success", artifact=threat_artifact)]
    )
    fill_adapter = RecordingAdapter(
        [StepResult(step_id="fill", operation_type="fill", status="success", changed_count=1)]
    )

    report = _execute(
        decision,
        {"enum_extract": extract_adapter, "threat_mapping": threat_adapter, "fill": fill_adapter},
        SessionFacts(
            has_logs=True,
            has_decoded_config=True,
            has_mapped_sub_rules=True,
            available_config_refs=("session.mapped_sub_rules",),
            available_fields=("event_type3",),
        ),
    )

    assert report.status == StepStatus.SUCCESS
    assert threat_adapter.calls[0][1] == {"extract": report.results[0]}
    assert fill_adapter.calls[0][1] == {"threat": report.results[1]}


def _enum_decision(target_field, plan_id="plan-field"):
    """构造单步 enum_extract 决策。"""
    return PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": plan_id,
            "steps": [
                {"step_id": "extract", "type": "enum_extract", "target_field": target_field}
            ],
        }
    )


def _success_enum_result():
    return StepResult(
        step_id="extract",
        operation_type="enum_extract",
        status=StepStatus.SUCCESS,
        artifact=EnumValuesArtifact(item_count=1, values=("value",)),
    )


def test枚举提取目标字段在原始日志键中时放行进适配器():
    """目标字段存在于日志体键（未进映射投影）时放行（回归 #66/#70 语义）。"""
    session = {
        "raw_log_lines": [
            "event_name=attack src=10.0.0.1",
            "event_name=scan src=10.0.0.2",
        ]
    }
    adapter = RecordingAdapter([_success_enum_result()])

    report = _execute_with_session(
        _enum_decision("event_name"),
        {"enum_extract": adapter},
        session,
        SessionFacts(has_logs=True, available_fields=("发生时间", "原始日志")),
    )

    assert report.results[0].status == StepStatus.SUCCESS
    assert report.results[0].artifact.values == ("value",)
    assert len(adapter.calls) == 1


def test枚举提取词典为空时放行保持旧行为():
    """日志体键与映射投影都提不出词典（如分隔符语料未分类）时不拦截（回归 #70）。"""
    session = {"raw_log_lines": ["aaa,bbb,ccc", "ddd,eee,fff"]}
    adapter = RecordingAdapter([_success_enum_result()])

    report = _execute_with_session(
        _enum_decision("ghost"), {"enum_extract": adapter}, session
    )

    assert report.results[0].status == StepStatus.SUCCESS
    assert len(adapter.calls) == 1


def test枚举提取目标字段不在任何词典时在适配器前拦截():
    """目标既不在日志体键也不在 available_fields 时 NEEDS_INPUT 列出可用字段（#196）。"""
    adapter = RecordingAdapter([])

    report = _execute_with_session(
        _enum_decision("ghost"),
        {"enum_extract": adapter},
        KV_SESSION,
        SessionFacts(has_logs=True, available_fields=("event_type3",)),
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "enum_target_field_not_found"
    assert report.results[0].choices == ("category", "event_type3", "src")
    assert adapter.calls == []
    message = report.results[0].message or ""
    assert "ghost" in message
    assert "可用的字段" in message
    assert "category" in message
    assert "src" in message
    assert "event_type3" in message


def test枚举提取目标字段大小写不同时不代改写并提示最接近():
    """与日志键仅大小写不同时不改写目标字段（链路字段逐字契约），拦截并提示最接近。"""
    adapter = RecordingAdapter([])

    report = _execute_with_session(
        _enum_decision("Category"), {"enum_extract": adapter}, KV_SESSION
    )

    assert report.results[0].status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "enum_target_field_not_found"
    message = report.results[0].message or ""
    assert "与「Category」最接近：category" in message
    assert adapter.calls == []


def test威胁链路四步计划来源字段不存在时首步追问且后续不执行():
    """链路 enum 步来源字段不存在时 💡 NEEDS_INPUT，后续威胁步骤零调用（#196）。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-threat-chain-abc",
            "steps": [
                {"step_id": "enum-1", "type": "enum_extract", "target_field": "abc"},
                {
                    "step_id": "threat-1",
                    "type": "threat_mapping",
                    "source_ref": "step:enum-1",
                    "depends_on": ["enum-1"],
                },
                {
                    "step_id": "add-1",
                    "type": "add_fields",
                    "field_name": "威胁类型",
                    "field_value": "%{abc}",
                    "value_type": "reference",
                    "rule_group": "threat",
                    "config_ref": "session.mapped_sub_rules",
                    "depends_on": ["threat-1"],
                },
                {
                    "step_id": "fill-1",
                    "type": "fill",
                    "fill_kind": "threat",
                    "target_fields": ["威胁类型"],
                    "source_ref": "step:threat-1",
                    "config_ref": "session.mapped_sub_rules",
                    "depends_on": ["threat-1"],
                },
            ],
        }
    )
    adapters = {
        "enum_extract": RecordingAdapter([]),
        "threat_mapping": RecordingAdapter([]),
        "add_fields": RecordingAdapter([]),
        "fill": RecordingAdapter([]),
    }

    report = _execute_with_session(
        decision,
        adapters,
        KV_SESSION,
        SessionFacts(
            has_logs=True,
            available_fields=("attack_name",),
            has_mapped_sub_rules=True,
            available_config_refs=("session.mapped_sub_rules",),
        ),
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert len(report.results) == 1
    assert report.results[0].step_id == "enum-1"
    assert report.results[0].error_code == "enum_target_field_not_found"
    assert all(adapter.calls == [] for adapter in adapters.values())


def test字段映射无原始字段候选时在适配器前拦截():
    """Planner 词典只剩标准名时仍以 fields_required 拦截（回归 #164）。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-field-mapping",
            "steps": [{"step_id": "mapping", "type": "field_mapping", "source_ref": "session.fields"}],
        }
    )
    adapter = RecordingAdapter([])

    report = _execute(
        decision,
        {"field_mapping": adapter},
        SessionFacts(available_fields=("源IP",), mappable_fields=()),
    )

    assert report.results[0].status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "fields_required"
    assert adapter.calls == []


def test枚举填充目标字段不在映射表时在适配器前拦截():
    """目标字段不在枚举映射表时以 mapping_target_unavailable 拦截（回归 #36）。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-enum-fill",
            "steps": [
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "enum",
                    "target_fields": ["missing"],
                    "source_ref": "session.enum_mapping_table",
                    "config_ref": "session.mapped_sub_rules",
                }
            ],
        }
    )
    adapter = RecordingAdapter([])

    report = _execute(
        decision,
        {"fill": adapter},
        SessionFacts(
            has_mapped_sub_rules=True,
            available_config_refs=("session.mapped_sub_rules",),
            enum_mapping_target_fields=("event_type3",),
        ),
    )

    assert report.results[0].status == StepStatus.NEEDS_INPUT
    assert report.results[0].error_code == "mapping_target_unavailable"
    assert adapter.calls == []


def test填充声称成功但零变更时判定失败():
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-no-change",
            "steps": [
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "enum",
                    "target_fields": ["event_type3"],
                    "source_ref": "session.enum_mapping_table",
                    "config_ref": "session.mapped_sub_rules",
                }
            ],
        }
    )
    adapter = RecordingAdapter(
        [StepResult(step_id="fill", operation_type="fill", status="success", changed_count=0)]
    )

    report = _execute(
        decision,
        {"fill": adapter},
        SessionFacts(
            has_decoded_config=True,
            has_mapped_sub_rules=True,
            available_config_refs=("session.mapped_sub_rules",),
            enum_mapping_target_fields=("event_type3",),
        ),
    )

    assert report.results[0].status == StepStatus.FAILED
    assert report.results[0].error_code == "no_effect"


def _rename_decision(field_value="僵尸网络入侵", value_type="fixed"):
    """构造 #148 复现形态的改名 delete+add 两步计划。"""
    return PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-rename",
            "steps": [
                {
                    "step_id": "del-1",
                    "type": "delete_fields",
                    "fields": ["事件名称", "事件级别"],
                    "target_rule_names": ["RUN_INFO"],
                    "config_ref": "session.mapped_sub_rules",
                },
                {
                    "step_id": "add-1",
                    "type": "add_fields",
                    "field_name": "事件名称",
                    "field_value": field_value,
                    "value_type": value_type,
                    "target_rule_names": ["RUN_INFO"],
                    "config_ref": "session.mapped_sub_rules",
                    "depends_on": ["del-1"],
                },
            ],
        }
    )


def test改名计划携带非法事件名时整计划执行前拦截():
    """add 的事件名非法：delete 不得先落盘删绑定对，任何适配器零调用（回归 #148）。"""
    session = {
        "mapped_sub_rules": [
            {"name": "RUN_INFO", "normalize": [{"index": "事件名称"}, {"index": "事件级别"}]}
        ]
    }
    delete_adapter = RecordingAdapter([])
    add_adapter = RecordingAdapter([])

    report = _execute_with_session(
        _rename_decision(),
        {"delete_fields": delete_adapter, "add_fields": add_adapter},
        session,
    )

    assert report.status == StepStatus.FAILED
    assert len(report.results) == 1
    assert report.results[0].step_id == "add-1"
    assert report.results[0].error_code == "invalid_event_name"
    assert delete_adapter.calls == []
    assert add_adapter.calls == []
    message = report.results[0].message or ""
    assert "必须是以下分类名之一" in message
    assert "网络攻击" in message
    assert "整份计划未执行" in message
    assert session["mapped_sub_rules"][0]["normalize"] == [
        {"index": "事件名称"},
        {"index": "事件级别"},
    ]


def test改名计划合法事件名仍按两步计划执行():
    """合法事件名不受计划级预校验影响，delete 与 add 都正常进入适配器。"""
    delete_adapter = RecordingAdapter(
        [StepResult(step_id="del-1", operation_type="delete_fields", status="success")]
    )
    add_adapter = RecordingAdapter(
        [StepResult(step_id="add-1", operation_type="add_fields", status="success")]
    )

    report = _execute_with_session(
        _rename_decision(field_value="终端告警"),
        {"delete_fields": delete_adapter, "add_fields": add_adapter},
        {"mapped_sub_rules": []},
    )

    assert report.status == StepStatus.SUCCESS
    assert len(delete_adapter.calls) == 1
    assert len(add_adapter.calls) == 1


def test事件名称引用型值在计划级拦截():
    """%{x} 引用型事件名在计划级即被拒绝，前面的 delete 不得先执行（回归 #148）。"""
    delete_adapter = RecordingAdapter([])
    add_adapter = RecordingAdapter([])

    report = _execute_with_session(
        _rename_decision(field_value="%{x}", value_type="reference"),
        {"delete_fields": delete_adapter, "add_fields": add_adapter},
        {"mapped_sub_rules": []},
    )

    assert report.status == StepStatus.FAILED
    assert report.results[0].error_code == "invalid_event_name"
    assert "不支持引用型值" in (report.results[0].message or "")
    assert delete_adapter.calls == []
    assert add_adapter.calls == []
