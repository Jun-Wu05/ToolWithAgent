"""子规则寻址与组批测试（#126 定案实现）。

覆盖：契约互斥与向后兼容、SessionFacts 名单投影、脚本 target_names 过滤
与 skip_existing、适配器名单校验/组解析/悬空守卫/事件名守卫作用域化、
fill 填充即解绑、标注明细行与覆盖警告。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from agent.shared.mapping_utils import unbind_fixed_fields
from contracts.planner_models import (
    AddFieldsStep,
    DecodeFieldsStep,
    DeleteFieldsStep,
    EventAnnotationRow,
    MergeFieldsStep,
)
from application.session_projection import build_session_facts
from application.execution import ExecutionContext
from application.adapters.field_skill import FieldSkillAdapter


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script(rel_path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _REPO_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def add_module():
    return _load_script(r"skills\add-fields\scripts\add_fields.py", "t_add_target")


@pytest.fixture(scope="module")
def delete_module():
    return _load_script(r"skills\delete-fields\scripts\delete_fields.py", "t_del_target")


def _annotated_config():
    """两条已标注子规则（威胁/非威胁各一）+ 一条未标注。"""
    def rule(name, event_name=None, level=None, extra_fields=None):
        filters = []
        if event_name:
            filters.append({
                "fields": {"事件名称": event_name, "事件级别": level},
                "name": "addFields", "id": "",
            })
        normalize = [{"index": "a", "result": ["1"]}]
        if event_name:
            normalize = normalize + [
                {"index": "事件名称", "result": [event_name]},
                {"index": "事件级别", "result": [level]},
            ]
        for field in extra_fields or []:
            normalize.append({"index": field, "result": ["v"]})
        return {
            "name": name,
            "normalize": normalize,
            "parser": {"filter": filters},
        }

    return [
        rule("暴力破解_kv_子规则", "网络攻击", "提醒"),
        rule("用户登录_json_子规则", "登录事件", "信息"),
        rule("未标注_子规则"),
    ]


def _context(session):
    return ExecutionContext(
        session=session, session_facts=build_session_facts(session), progress_sink=None
    )


def _run(adapter, step, session):
    return asyncio.run(adapter.execute(step, _context(session), {}))


# ---------------------------------------------------------------------------
# 契约
# ---------------------------------------------------------------------------


def test契约寻址参数互斥():
    """target_rule_names 与 rule_group 不能同时指定。"""
    with pytest.raises(Exception):
        DeleteFieldsStep(
            step_id="d1", type="delete_fields", fields=("a",),
            target_rule_names=("rule-1",), rule_group="threat",
            config_ref="session.mapped_sub_rules",
        )
    with pytest.raises(Exception):
        MergeFieldsStep(
            step_id="m1", type="merge_fields", source_fields=("a", "b"), target_field="d",
            target_rule_names=("rule-1",), rule_group="non_threat",
            config_ref="session.mapped_sub_rules",
        )


def test契约缺省值向后兼容():
    """不带寻址参数的步骤与旧语义一致（全部 entity、无跳过）。"""
    step = AddFieldsStep(
        step_id="a1", type="add_fields", field_name="x", field_value="1",
        config_ref="session.decoded_config",
    )
    assert step.target_rule_names == ()
    assert step.rule_group == "all"
    assert step.skip_existing is False
    decode = DecodeFieldsStep(
        step_id="c1", type="decode_fields", fields=("a",),
        config_ref="session.decoded_config",
    )
    assert decode.rule_group == "all"


# ---------------------------------------------------------------------------
# SessionFacts 名单投影
# ---------------------------------------------------------------------------


def test会话事实暴露子规则名单():
    """mapped_sub_rule_names / decoded_config_rule_names 去重保序投影。"""
    session = {
        "mapped_sub_rules": [{"name": "rule-a"}, {"name": "rule-b"}, {"name": "rule-a"}],
        "decoded_data": [{"name": "entry-1"}, {"name": "entry-1"}, {"name": "sub-9"}],
    }
    facts = build_session_facts(session)
    assert facts.mapped_sub_rule_names == ("rule-a", "rule-b")
    assert facts.decoded_config_rule_names == ("entry-1", "sub-9")


# ---------------------------------------------------------------------------
# 脚本 target_names / skip_existing
# ---------------------------------------------------------------------------


def test脚本按名过滤且名单外透传(add_module, delete_module):
    """target_names 只改目标 entity；名单外原样保留。"""
    data = _annotated_config()

    added = add_module.add_field(data, "备注", "重点", target_names=["暴力破解_kv_子规则"])
    assert added["status"] == "success"
    by_name = {e["name"]: e for e in added["data"]}
    assert "备注" in [i["index"] for i in by_name["暴力破解_kv_子规则"]["normalize"]]
    assert "备注" not in [i["index"] for i in by_name["用户登录_json_子规则"]["normalize"]]
    assert "目标 1 个" in added["message"]

    deleted = delete_module.delete_field(
        added["data"], ["事件名称"], target_names=["用户登录_json_子规则"]
    )
    assert deleted["status"] == "success"
    by_name = {e["name"]: e for e in deleted["data"]}
    assert "事件名称" not in [i["index"] for i in by_name["用户登录_json_子规则"]["normalize"]]
    assert "事件名称" in [i["index"] for i in by_name["暴力破解_kv_子规则"]["normalize"]]


def test脚本skip_existing跳过而非失败(add_module):
    """同名字段已存在的 entity 跳过并计数，不再整体失败。"""
    data = _annotated_config()
    result = add_module.add_field(
        data, "事件名称", "终端告警", target_names=["暴力破解_kv_子规则"], skip_existing=True
    )
    assert result["status"] == "success"
    assert "已存在该字段，跳过" in result["message"]
    # 未标注子规则不受目标限制外影响，事件名称仍是新加的
    added_fresh = add_module.add_field(
        data, "事件名称", "终端告警", target_names=["未标注_子规则"], skip_existing=True
    )
    assert added_fresh["status"] == "success"
    indexes = [i["index"] for i in added_fresh["data"][2]["normalize"]]
    assert "事件名称" in indexes


# ---------------------------------------------------------------------------
# 适配器：名单校验 / 组解析 / 悬空守卫 / 事件名守卫作用域
# ---------------------------------------------------------------------------


def test适配器未知子规则名返回rule_name_not_found():
    """点名名单外的子规则被拒并列出可用名单。"""
    step = AddFieldsStep(
        step_id="a1", type="add_fields", field_name="备注", field_value="重点",
        target_rule_names=("不存在的规则",),
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, {"mapped_sub_rules": _annotated_config()})
    assert result.status.value == "failed"
    assert result.error_code == "rule_name_not_found"
    assert "暴力破解_kv_子规则" in result.message


def test适配器威胁组解析只命中威胁子规则():
    """rule_group=threat 按已标注事件名称确定性分组。"""
    step = AddFieldsStep(
        step_id="a1", type="add_fields", field_name="备注", field_value="重点",
        rule_group="threat", config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _annotated_config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success"
    by_name = {e["name"]: e for e in session["mapped_sub_rules"]}
    assert "备注" in [i["index"] for i in by_name["暴力破解_kv_子规则"]["normalize"]]
    assert "备注" not in [i["index"] for i in by_name["用户登录_json_子规则"]["normalize"]]
    assert "备注" not in [i["index"] for i in by_name["未标注_子规则"]["normalize"]]


def test适配器无标注时组批返回event_annotation_required():
    """没有任何事件名称标注时按组批被拒。"""
    step = DeleteFieldsStep(
        step_id="d1", type="delete_fields", fields=("a",),
        rule_group="non_threat", config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": [{"name": "r", "normalize": [{"index": "a"}], "parser": {"filter": []}}]}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "failed"
    assert result.error_code == "event_annotation_required"


def test适配器删除悬空引用被拒():
    """merger 源字段与 %{字段} 占位引用被删字段时拒绝。"""
    config = [
        {
            "name": "r1",
            "normalize": [
                {"index": "a", "result": ["1"]},
                {"index": "b", "result": ["2"]},
                {"index": "reqheader", "result": ["h"]},
            ],
            "parser": {"filter": [
                {"name": "merger", "field": "d", "sep": "", "id": "", "fields": ["a", "b"]},
                {"fields": {"请求头": "%{reqheader}"}, "name": "addFields", "id": ""},
            ]},
        }
    ]
    step = DeleteFieldsStep(
        step_id="d1", type="delete_fields", fields=("a",),
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, {"decoded_data": config})
    assert result.status.value == "failed"
    assert result.error_code == "field_reference_conflict"
    assert "merger" in result.message

    step_placeholder = DeleteFieldsStep(
        step_id="d2", type="delete_fields", fields=("reqheader",),
        config_ref="session.decoded_config",
    )
    result2 = _run(FieldSkillAdapter(), step_placeholder, {"decoded_data": config})
    assert result2.status.value == "failed"
    assert "%{reqheader}" in result2.message


def test事件名守卫只检查目标范围():
    """事件级别存在于非目标子规则时不拦截联动；存在于目标内才拦截。"""
    step_ok = AddFieldsStep(
        step_id="a1", type="add_fields", field_name="事件名称", field_value="终端告警",
        target_rule_names=("未标注_子规则",), config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step_ok, {"mapped_sub_rules": _annotated_config()})
    assert result.status.value == "success"

    step_conflict = AddFieldsStep(
        step_id="a2", type="add_fields", field_name="事件名称", field_value="终端告警",
        target_rule_names=("暴力破解_kv_子规则",), config_ref="session.mapped_sub_rules",
    )
    result2 = _run(FieldSkillAdapter(), step_conflict, {"mapped_sub_rules": _annotated_config()})
    assert result2.status.value == "failed"
    assert result2.error_code == "event_level_conflict"


def testskip_existing步骤级联生效():
    """skip_existing=true 的加字段步骤对已存在目标跳过不失败。"""
    step = AddFieldsStep(
        step_id="a1", type="add_fields", field_name="事件名称", field_value="终端告警",
        target_rule_names=("暴力破解_kv_子规则", "未标注_子规则"),
        skip_existing=True, config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _annotated_config()}
    result = _run(FieldSkillAdapter(), step, session)
    # 暴力破解已有事件名称（跳过），未标注子规则正常新增
    assert result.status.value == "success"
    by_name = {e["name"]: e for e in session["mapped_sub_rules"]}
    assert "已存在该字段，跳过" in result.message
    assert "事件名称" in [i["index"] for i in by_name["未标注_子规则"]["normalize"]]


# ---------------------------------------------------------------------------
# fill 填充即解绑
# ---------------------------------------------------------------------------


def test解绑助手删除绑定键保留normalize():
    """unbind_fixed_fields 只删 addFields 绑定键，normalize 条目保留。"""
    config = [
        {
            "name": "r1",
            "normalize": [
                {"index": "事件级别", "result": ["提醒"], "mappings": []},
                {"index": "a", "result": ["1"]},
            ],
            "parser": {"filter": [
                {"fields": {"事件名称": "网络攻击", "事件级别": "提醒"},
                 "name": "addFields", "id": ""},
            ]},
        }
    ]
    updated, unbound = unbind_fixed_fields(config, ["事件级别"])
    assert unbound == ["r1"]
    filter_fields = updated[0]["parser"]["filter"][0]["fields"]
    assert "事件级别" not in filter_fields
    assert filter_fields["事件名称"] == "网络攻击"  # 非目标绑定键保留
    indexes = [i["index"] for i in updated[0]["normalize"]]
    assert "事件级别" in indexes  # normalize 保留（填充目标）
    # 原对象未动
    assert "事件级别" in config[0]["parser"]["filter"][0]["fields"]


def test解绑跳过引用值绑定():
    """%{字段} 引用绑定不在解除范围（#173）：威胁类型链路的取值语义依赖引用存活。"""
    config = [
        {
            "name": "r3",
            "normalize": [{"index": "威胁类型", "mappings": []}],
            "parser": {"filter": [
                {"fields": {"威胁类型": "%{attack_type}"},
                 "name": "addFields", "id": ""},
            ]},
        }
    ]
    updated, unbound = unbind_fixed_fields(config, ["威胁类型"])
    assert unbound == []
    assert updated[0]["parser"]["filter"][0]["fields"]["威胁类型"] == "%{attack_type}"


def test解绑清空的过滤器整体移除():
    """绑定 addFields 的键被清空时整个过滤器移除，不留空 addFields。"""
    config = [
        {
            "name": "r2",
            "normalize": [{"index": "事件名称", "result": ["网络攻击"]}],
            "parser": {"filter": [
                {"fields": {"product": ""}, "name": "addFields", "id": "additional_fields_filter"},
                {"fields": {"事件名称": "网络攻击", "事件级别": "提醒"},
                 "name": "addFields", "id": ""},
            ]},
        }
    ]
    updated, unbound = unbind_fixed_fields(config, ["事件名称", "事件级别"])
    assert unbound == ["r2"]
    remaining = updated[0]["parser"]["filter"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == "additional_fields_filter"


def test枚举填充事件级别即解绑():
    """EnumFillAdapter 对事件级别填充：先解绑再写 mappings，消息注明。"""
    from application.adapters.enum_fill import EnumFillAdapter
    from contracts.planner_models import FillStep

    config = [
        {
            "name": "r1",
            "normalize": [{"index": "事件级别", "result": ["提醒"], "mappings": []}],
            "parser": {"filter": [
                {"fields": {"事件名称": "网络攻击", "事件级别": "提醒"},
                 "name": "addFields", "id": ""},
            ]},
        }
    ]
    session = {
        "decoded_data": config,
        "enum_preview": [
            {"目标字段": "事件级别", "orgValue": "1", "mappingValue": "高危"},
        ],
    }
    step = FillStep(
        step_id="f1", type="fill", fill_kind="enum",
        target_fields=("事件级别",),
        source_ref="session.enum_mapping_table",
        config_ref="session.decoded_config",
    )
    result = _run(EnumFillAdapter(), step, session)
    assert result.status.value == "success"
    assert "已解除 1 条规则的固定值绑定" in result.message
    rule = session["decoded_data"][0]
    bound_keys = rule["parser"]["filter"][0]["fields"]
    assert "事件级别" not in bound_keys
    mappings = rule["normalize"][0]["mappings"]
    assert mappings and mappings[0]["mappingValue"] == "高危"


# ---------------------------------------------------------------------------
# 标注明细行与覆盖警告
# ---------------------------------------------------------------------------


def _llm_json(results):
    def _call(prompt: str) -> str:
        import json
        return json.dumps({"results": results}, ensure_ascii=False)
    return _call


def test标注明细行进入产物并区分待确认():
    """_annotate_event_names 返回 judged/uncertain 明细行（#126 展示分离数据源）。"""
    from application.adapters.field_mapping import FieldMappingAdapter

    fake = _llm_json([
        {"rule_name": "暴力破解_kv_子规则", "event_name": "网络攻击", "group": "threat", "reason": "x"},
    ])
    adapter = FieldMappingAdapter(team=None, event_classifier=fake)
    rules = _annotated_config()[:2]
    step_outcome = asyncio.run(
        adapter._annotate_event_names(_fm_step(), _context({}), rules)
    )
    annotated, summary, rows = step_outcome
    assert len(rows) == 2
    by_name = {row.rule_name: row for row in rows}
    judged = by_name["暴力破解_kv_子规则"]
    assert isinstance(judged, EventAnnotationRow)
    assert (judged.event_name, judged.event_level, judged.status) == ("网络攻击", "提醒", "judged")
    uncertain = by_name["用户登录_json_子规则"]
    assert uncertain.status == "uncertain"
    assert uncertain.event_name == ""
    assert "待人工确认" in summary


def _fm_step():
    from contracts.planner_models import FieldMappingStep
    return FieldMappingStep(
        step_id="mapping", type="field_mapping", source_ref="session.fields"
    )


def test渲染标注明细块():
    """标注块含表头、judged 行与待确认行。"""
    from web.plan_renderer import _render_event_annotation_block

    block = _render_event_annotation_block([
        EventAnnotationRow(rule_name="r1", event_name="网络攻击", event_level="提醒"),
        EventAnnotationRow(rule_name="r2", status="uncertain"),
    ])
    assert "事件名称标注" in block
    assert "| 子规则 | 事件名称 | 事件级别 |" in block
    assert "| r1 | 网络攻击 | 提醒 |" in block
    assert "| r2 | ⚠️ 待人工确认 | — |" in block
