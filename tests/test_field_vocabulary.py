"""字段词汇解析测试（#146）：标准名↔原始名确定性解析与引用校验。

线上回归背景：用户以映射表展示的标准字段名（HTTP请求头）指称字段，
系统按原始 index（req_head）操作导致 field_not_found；add_fields 的
%{X} 引用不校验目标产生静默坏引用。
"""

from __future__ import annotations

import asyncio

from contracts.planner_models import (
    AddFieldsStep,
    DeleteFieldsStep,
    MergeFieldsStep,
    RemoveMappingStep,
)
from application.session_projection import build_session_facts
from application.execution import ExecutionContext
from application.adapters.shared import (
    field_vocabulary,
    format_field_vocabulary,
    resolve_field_names,
)
from application.adapters.field_skill import FieldSkillAdapter


def _config():
    """req_head/req_body 已映射标准名；src_ip/sip_identify 同映射「源地址」。"""
    return [
        {
            "name": "IPS_kv_子规则",
            "normalize": [
                {"index": "req_head", "field": "HTTP请求头", "result": ["h"]},
                {"index": "req_body", "field": "HTTP请求体", "result": ["b"]},
                {"index": "resp_head", "field": "HTTP响应头", "result": ["rh"]},
                {"index": "src_ip", "field": "源地址", "result": ["1.1.1.1"]},
                {"index": "sip_identify", "field": "源地址", "result": ["2.2.2.2"]},
            ],
            "parser": {"filter": []},
        }
    ]


def _run(adapter, step, session):
    return asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(
                session=session,
                session_facts=build_session_facts(session),
                progress_sink=None,
            ),
            {},
        )
    )


# ---------------------------------------------------------------------------
# 解析助手纯函数
# ---------------------------------------------------------------------------


def test解析助手精确index优先():
    """index 精确命中原样通过（即使同名标准字段也存在）。"""
    resolved, problems = resolve_field_names(_config(), ["req_head"])
    assert resolved == {"req_head": "req_head"}
    assert problems == []


def test解析助手标准名唯一命中():
    """标准字段名唯一对应 index 时解析为原始 index。"""
    resolved, problems = resolve_field_names(_config(), ["HTTP请求头", "HTTP请求体"])
    assert resolved == {"HTTP请求头": "req_head", "HTTP请求体": "req_body"}
    assert problems == []


def test解析助手歧义标准名列候选():
    """多个 index 同标准名 → ambiguous 问题列候选，不猜。"""
    resolved, problems = resolve_field_names(_config(), ["源地址"])
    assert "源地址" not in resolved
    assert problems[0]["kind"] == "ambiguous"
    assert set(problems[0]["candidates"]) == {"src_ip", "sip_identify"}


def test解析助手零命中返回not_found():
    resolved, problems = resolve_field_names(_config(), ["不存在字段"])
    assert problems[0]["kind"] == "not_found"


def test词汇对照表格式化():
    """对照表 原始名(标准名) 格式，供错误消息使用。"""
    text = format_field_vocabulary(_config())
    assert "req_head(HTTP请求头)" in text
    assert "src_ip(源地址)" in text


# ---------------------------------------------------------------------------
# 适配器路径（#146 线上报错回归）
# ---------------------------------------------------------------------------


def test合并指令标准名源字段自动解析():
    """「合并HTTP请求头和HTTP请求体」经适配器解析为 req_head/req_body 成功。"""
    step = MergeFieldsStep(
        step_id="m1", type="merge_fields",
        source_fields=("HTTP请求头", "HTTP请求体"),
        target_field="响应内容", sep="",
        config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success", result.message
    merger = [
        f for f in session["mapped_sub_rules"][0]["parser"]["filter"]
        if f.get("name") == "merger"
    ]
    assert merger[0]["fields"] == ["req_head", "req_body"]
    assert "字段解析：HTTP请求头→req_head、HTTP请求体→req_body" in result.message


def test合并指令歧义标准名返回专用错误():
    """源字段「源地址」歧义 → field_name_ambiguous 列候选。"""
    step = MergeFieldsStep(
        step_id="m1", type="merge_fields",
        source_fields=("源地址", "req_body"),
        target_field="x", sep="",
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, {"mapped_sub_rules": _config()})
    assert result.status.value == "failed"
    assert result.error_code == "field_name_ambiguous"
    assert "src_ip" in result.message and "sip_identify" in result.message


def test合并指令零命中错误含两套词汇对照():
    step = MergeFieldsStep(
        step_id="m1", type="merge_fields",
        source_fields=("ghost", "req_body"), target_field="x", sep="",
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, {"mapped_sub_rules": _config()})
    assert result.status.value == "failed"
    assert result.error_code == "field_not_found"
    assert "req_head(HTTP请求头)" in result.message


def test删除指令标准名解析():
    step = DeleteFieldsStep(
        step_id="d1", type="delete_fields", fields=("HTTP请求头",),
        config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success", result.message
    indexes = [e["index"] for e in session["mapped_sub_rules"][0]["normalize"]]
    assert "req_head" not in indexes
    assert "字段解析：HTTP请求头→req_head" in result.message


def test添加引用字段标准名解析与改写():
    """%{HTTP响应头} 解析并改写为 %{resp_head}，消息注明。"""
    step = AddFieldsStep(
        step_id="a1", type="add_fields",
        field_name="请求内容", field_value="%{HTTP响应头}",
        value_type="reference",
        config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success", result.message
    addfields = [
        f for f in session["mapped_sub_rules"][0]["parser"]["filter"]
        if f.get("name") == "addFields" and f.get("id") == ""
    ]
    assert addfields[-1]["fields"]["请求内容"] == "%{resp_head}"
    assert "HTTP响应头→resp_head" in result.message


def test添加引用字段目标不可解析被拒绝():
    """%{ghost} → reference_target_not_found，不写入坏引用。"""
    step = AddFieldsStep(
        step_id="a1", type="add_fields",
        field_name="请求内容", field_value="%{ghost}",
        value_type="reference",
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, {"mapped_sub_rules": _config()})
    assert result.status.value == "failed"
    assert result.error_code == "reference_target_not_found"


def test取消映射标准名目标解析():
    """「取消HTTP请求头的映射」解析为 req_head 后清除。"""
    config = _config()
    config[0]["normalize"][0]["mappings"] = [
        {"mappingType": "EQUAL", "orgValue": "a", "mappingValue": "b"}
    ]
    session = {"mapped_sub_rules": config}
    step = RemoveMappingStep(
        step_id="r1", type="remove_mapping", target_fields=("HTTP请求头",),
        config_ref="session.mapped_sub_rules",
    )
    result = _run(_RemoveMappingRunner(), step, session)
    assert result.status.value == "success", result.message
    assert session["mapped_sub_rules"][0]["normalize"][0]["mappings"] == []
    assert "HTTP请求头→req_head" in result.message


def _RemoveMappingRunner():
    from application.adapters.remove_mapping import RemoveMappingAdapter
    return RemoveMappingAdapter()


def test解析限定目标范围():
    """非目标 entity 的同名标准字段不参与解析（#126 寻址作用域）。"""
    config = _config() + [
        {
            "name": "other_rule",
            "normalize": [
                {"index": "alt_head", "field": "HTTP请求头", "result": ["x"]},
            ],
            "parser": {"filter": []},
        }
    ]
    # 限定目标 other_rule 时，HTTP请求头 解析为 alt_head 而非 req_head
    resolved, problems = resolve_field_names(config, ["HTTP请求头"], ["other_rule"])
    assert resolved == {"HTTP请求头": "alt_head"}
    # 不限定时出现歧义
    resolved_all, problems_all = resolve_field_names(config, ["HTTP请求头"])
    assert problems_all and problems_all[0]["kind"] == "ambiguous"
