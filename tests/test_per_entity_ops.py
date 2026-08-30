"""per-entity 自适应与绑定对联动删除测试（#147）。

线上回归：三条子规则字段集不同（req_url/req_query 仅 AUDIT/IPS 有、
req_head 仅 IPS 有），正确的字段名也触发 field_not_found；delete 脚本
missing 被逐 entity 覆盖导致计数为 0 但 IPS 实删；事件级别可单独删除
留下绑定残缺。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from contracts.planner_models import (
    DeleteFieldsStep,
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
def merge_module():
    return _load_script(r"skills\merge-fields\scripts\merge_fields.py", "t_merge_pe")


@pytest.fixture(scope="module")
def delete_module():
    return _load_script(r"skills\delete-fields\scripts\delete_fields.py", "t_del_pe")


@pytest.fixture(scope="module")
def decode_module():
    return _load_script(
        r"skills\base64-decode-fields\scripts\decode_fields.py", "t_dec_pe"
    )


def _diverse_config():
    """复刻线上场景：AUDIT/IPS/RUN_INFO 三子规则字段集不同。"""
    def rule(name, fields, event=None, standard_map=None):
        normalize = []
        for f in fields:
            entry = {"index": f, "result": [f + "_v"]}
            if standard_map and f in standard_map:
                entry["field"] = standard_map[f]
            normalize.append(entry)
        if event:
            normalize += [
                {"index": "事件名称", "result": [event]},
                {"index": "事件级别", "result": ["提醒" if event == "网络攻击" else "信息"]},
            ]
        return {"name": name, "normalize": normalize, "parser": {"filter": []}}

    standard = {"req_head": "HTTP请求头", "req_body": "HTTP请求体"}
    return [
        rule("AUDIT_kv_子规则", ["req_url", "req_query", "req_body"], "审计事件", standard),
        rule("IPS_kv_子规则", ["req_url", "req_query", "req_head", "req_body"], "网络攻击", standard),
        rule("RUN_INFO_kv_子规则", ["content", "count"], "资源监控"),
    ]


def _context(session):
    return ExecutionContext(
        session=session, session_facts=build_session_facts(session), progress_sink=None
    )


def _run(adapter, step, session):
    return asyncio.run(adapter.execute(step, _context(session), {}))


# ---------------------------------------------------------------------------
# merge per-entity（线上指令「把req_url 和 req_query 合并成 合并字段」）
# ---------------------------------------------------------------------------


def test合并跨子规则正确字段名自适应应用(merge_module):
    """AUDIT/IPS 有全部源、RUN_INFO 缺 → 前两条合并、RUN_INFO 跳过并按名报告。"""
    result = merge_module.merge_fields(
        _diverse_config(), ["req_url", "req_query"], "合并字段", ""
    )
    assert result["status"] == "success", result["message"]
    by_name = {e["name"]: e for e in result["data"]}
    assert "合并字段" in [i["index"] for i in by_name["AUDIT_kv_子规则"]["normalize"]]
    assert "合并字段" in [i["index"] for i in by_name["IPS_kv_子规则"]["normalize"]]
    assert "合并字段" not in [
        i["index"] for i in by_name["RUN_INFO_kv_子规则"]["normalize"]
    ]
    assert "成功合并 2 个 entity" in result["message"]
    assert "RUN_INFO_kv_子规则（缺 req_url、req_query）" in result["message"]


def test合并全部子规则都缺源报field_not_found(merge_module):
    """所有目标 entity 都没有该字段 → 真错误并列并集词表。"""
    result = merge_module.merge_fields(
        _diverse_config(), ["req_head", "ghost_field"], "合并字段", ""
    )
    assert result["status"] == "error"
    assert "不存在于任何（目标）子规则" in result["message"]
    assert "req_head" in result["message"]  # 并集里出现（IPS 有）


def test合并目标已存在的entity跳过(merge_module):
    """目标字段已存在的 entity 跳过而非整体失败。"""
    config = _diverse_config()
    config[0]["normalize"].append({"index": "已有目标", "result": ["x"]})
    config[1]["normalize"].append({"index": "已有目标", "result": ["y"]})
    result = merge_module.merge_fields(
        config, ["req_url", "req_query"], "已有目标", ""
    )
    assert result["status"] == "success"
    # AUDIT/IPS 目标已存在跳过；RUN_INFO 缺源跳过 → 应用 0 但不整体报错
    assert "成功合并 0 个 entity" in result["message"]
    assert "AUDIT_kv_子规则（目标 '已有目标' 已存在）" in result["message"]
    assert "IPS_kv_子规则（目标 '已有目标' 已存在）" in result["message"]
    assert "RUN_INFO_kv_子规则（缺 req_url、req_query）" in result["message"]


# ---------------------------------------------------------------------------
# delete per-entity（线上指令「删除字段http请求头」missing 覆盖 bug）
# ---------------------------------------------------------------------------


def test删除部分子规则有字段时计数正确(delete_module):
    """req_head 仅 IPS 有 → 从 IPS 真删、计数 1；AUDIT/RUN_INFO 跳过并按名报告。"""
    result = delete_module.delete_field(_diverse_config(), ["req_head"])
    assert result["status"] == "success", result["message"]
    by_name = {e["name"]: e for e in result["data"]}
    assert "req_head" not in [
        i["index"] for i in by_name["IPS_kv_子规则"]["normalize"]
    ]
    assert "成功从 1 个 entity 删除 1 个字段" in result["message"]
    assert "AUDIT_kv_子规则（缺 req_head）" in result["message"]
    assert "RUN_INFO_kv_子规则（缺 req_head）" in result["message"]
    # 不再出现误报「未找到」（旧 bug：missing 被最后一条 entity 覆盖）
    assert "未找到字段" not in result["message"]


def test删除所有子规则都没有的字段报未找到(delete_module):
    """字段在任何子规则都不存在 → not_found 归入消息。"""
    result = delete_module.delete_field(_diverse_config(), ["ghost"])
    assert result["status"] == "success"
    assert "未找到字段: ghost" in result["message"]
    assert "不存在于任何子规则" in result["message"]


def test删除多字段per_entity混合计数(delete_module):
    """req_head（仅 IPS）+ req_url（AUDIT/IPS）→ IPS 删 2 个、AUDIT 删 1 个、RUN_INFO 跳过。"""
    result = delete_module.delete_field(_diverse_config(), ["req_head", "req_url"])
    assert result["status"] == "success"
    assert "成功从 2 个 entity 删除 3 个字段" in result["message"]
    # AUDIT 有 req_url（部分可删）→ 正常执行不跳过；RUN_INFO 两个都缺 → 跳过
    assert "RUN_INFO_kv_子规则（缺 req_head、req_url）" in result["message"]
    by_name = {e["name"]: e for e in result["data"]}
    audit_indexes = [i["index"] for i in by_name["AUDIT_kv_子规则"]["normalize"]]
    ips_indexes = [i["index"] for i in by_name["IPS_kv_子规则"]["normalize"]]
    assert "req_url" not in audit_indexes and "req_head" not in audit_indexes  # AUDIT 删了 req_url
    assert "req_url" not in ips_indexes and "req_head" not in ips_indexes    # IPS 删了两个


# ---------------------------------------------------------------------------
# decode per-entity
# ---------------------------------------------------------------------------


def test解码缺字段entity跳过并报告(decode_module):
    """req_head 仅 IPS 有 → 只给 IPS 启用解码，其余跳过。"""
    result = decode_module.decode_fields(_diverse_config(), ["req_head"])
    assert result["status"] == "success", result["message"]
    by_name = {e["name"]: e for e in result["data"]}
    ips_filters = by_name["IPS_kv_子规则"]["parser"]["filter"]
    assert any("Base64Decode(req_head)" in str(f) for f in ips_filters)
    assert "AUDIT_kv_子规则（缺 req_head）" in result["message"]
    assert "RUN_INFO_kv_子规则（缺 req_head）" in result["message"]


# ---------------------------------------------------------------------------
# 适配器：绑定对联动删除 + 近邻提示
# ---------------------------------------------------------------------------


def test删除事件级别联动删除绑定对():
    """删 事件级别 → 事件名称+事件级别 一起删（#147 绑定残缺防护）。"""
    step = DeleteFieldsStep(
        step_id="d1", type="delete_fields", fields=("事件级别",),
        config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _diverse_config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success", result.message
    assert "已联动删除绑定对（事件名称+事件级别）" in result.message
    for rule in session["mapped_sub_rules"]:
        indexes = [i["index"] for i in rule["normalize"]]
        assert "事件名称" not in indexes
        assert "事件级别" not in indexes


def test删除事件名称同样联动绑定对():
    step = DeleteFieldsStep(
        step_id="d1", type="delete_fields", fields=("事件名称",),
        config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _diverse_config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success", result.message
    assert "已联动删除绑定对" in result.message


def test适配器合并线上指令端到端():
    """「把req_url 和 req_query 合并成 合并字段」端到端（#147 线上报错回归）。"""
    step = MergeFieldsStep(
        step_id="m1", type="merge_fields",
        source_fields=("req_url", "req_query"), target_field="合并字段", sep="",
        config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _diverse_config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success", result.message
    assert "成功合并 2 个 entity" in result.message
    assert "RUN_INFO_kv_子规则（缺 req_url、req_query）" in result.message


def test适配器删除线上指令端到端():
    """「删除字段http请求头」（标准名→req_head，仅 IPS 有）端到端。"""
    step = DeleteFieldsStep(
        step_id="d1", type="delete_fields", fields=("HTTP请求头",),
        config_ref="session.mapped_sub_rules",
    )
    session = {"mapped_sub_rules": _diverse_config()}
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status.value == "success", result.message
    assert "成功从 1 个 entity 删除 1 个字段" in result.message
    assert "字段解析：HTTP请求头→req_head" in result.message
    # 不再误报未找到
    assert "未找到字段" not in result.message


def test近邻提示字段名笔误():
    """reqquery（漏下划线）→ 错误消息含「您是不是要找：req_query」。"""
    step = MergeFieldsStep(
        step_id="m1", type="merge_fields",
        source_fields=("reqquery", "req_url"), target_field="合并字段", sep="",
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, {"mapped_sub_rules": _diverse_config()})
    assert result.status.value == "failed"
    assert result.error_code == "field_not_found"
    assert "req_query" in result.message
