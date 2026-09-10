"""字段调整 skills 的脚本、契约与适配器测试（PRD #124）。

覆盖三档接缝：
- skills 脚本纯函数（filter=null / 空 normalize / 保留字段 / 冲突）
- 类型化契约（add/delete/merge 步骤校验）
- FieldSkillAdapter（session 读写回、稳定错误码、事件名称绑定守卫）
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
from pathlib import Path

import pytest

from contracts.planner_models import (
    AddFieldsStep,
    DeleteFieldsStep,
    MergeFieldsStep,
    PlanDecision,
    StepStatus,
)
from application.session_projection import build_session_facts
from application.execution import ExecutionContext
from application.adapters.field_skill import (
    FIELD_SKILL_REGISTRY,
    FieldSkillAdapter,
    _load_skill_function,
)


# ---------------------------------------------------------------------------
# 测试数据与工具
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script(rel_path: str, module_name: str):
    """按 skills 脚本真实路径加载（与适配器同一加载方式）。"""
    spec = importlib.util.spec_from_file_location(
        module_name, _REPO_ROOT / rel_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def add_module():
    """加载添加字段脚本。"""
    return _load_script(r"skills\add-fields\scripts\add_fields.py", "t_add_fields")


@pytest.fixture(scope="module")
def delete_module():
    """加载删除字段脚本。"""
    return _load_script(r"skills\delete-fields\scripts\delete_fields.py", "t_delete_fields")


@pytest.fixture(scope="module")
def merge_module():
    """加载合并字段脚本。"""
    return _load_script(r"skills\merge-fields\scripts\merge_fields.py", "t_merge_fields")


def _sample_entities():
    """入口规则（filter=null）+ 子规则混合数据。"""
    return [
        {
            "name": "entry",
            "normalize": [
                {"index": "a", "result": ["1"]},
                {"index": "b", "result": ["2"]},
            ],
            "parser": {"name": "nothing", "filter": None},
        },
        {
            "name": "sub",
            "normalize": [
                {"index": "a", "result": ["x"]},
                {"index": "b", "result": ["y"]},
                {"index": "original_log", "result": ["raw"]},
            ],
            "parser": {"filter": []},
        },
    ]


def _context(session):
    """构造最小执行上下文。"""
    return ExecutionContext(
        session=session,
        session_facts=build_session_facts(session),
        progress_sink=None,
    )


# ---------------------------------------------------------------------------
# skills 脚本纯函数 seam
# ---------------------------------------------------------------------------


def test添加字段在入口规则filter为null时初始化并追加(add_module):
    """入口规则模板 filter=null 不再崩溃，addFields 正确追加。"""
    result = add_module.add_field(_sample_entities(), "主机ip", "1.1.1.1")
    assert result["status"] == "success"
    entry = result["data"][0]
    assert entry["parser"]["filter"][0] == {
        "name": "addFields",
        "id": "",
        "fields": {"主机ip": "1.1.1.1"},
    }
    assert entry["normalize"][-1]["index"] == "主机ip"
    assert entry["normalize"][-1]["result"] == ["1.1.1.1"]


def test添加字段撤销同名删除标记并保留其他删除字段(add_module):
    entities = _sample_entities()
    entities[0]["parser"]["filter"] = [
        {
            "name": "removeFields",
            "id": "",
            "fields": ["威胁类型", "旧字段"],
        }
    ]
    entities[1]["parser"]["filter"] = [
        {"name": "removeFields", "id": "", "fields": ["威胁类型"]}
    ]

    result = add_module.add_field(entities, "威胁类型", "%{alarm_name}")

    assert result["status"] == "success"
    first_filters = result["data"][0]["parser"]["filter"]
    second_filters = result["data"][1]["parser"]["filter"]
    assert first_filters[0] == {
        "name": "removeFields",
        "id": "",
        "fields": ["旧字段"],
    }
    assert all(item.get("name") != "removeFields" for item in second_filters)


def test添加字段引用型值原样保留(add_module):
    """%{index} 引用值不做替换，原样存储由运行时解析。"""
    result = add_module.add_field(_sample_entities(), "请求头", "%{a}")
    assert result["status"] == "success"
    assert result["data"][0]["parser"]["filter"][0]["fields"] == {"请求头": "%{a}"}
    assert result["data"][0]["normalize"][-1]["result"] == ["%{a}"]


def test添加字段已存在时拒绝且不改原数据(add_module):
    """字段冲突返回 error；deepcopy 保证输入不被部分修改。"""
    entities = _sample_entities()
    result = add_module.add_field(entities, "a", "9")
    assert result["status"] == "error"
    assert "已存在" in result["message"]
    assert entities[0]["parser"]["filter"] is None  # 原数据未动


def test添加字段空normalize跳过计数如实(add_module):
    """无 normalize 的 entity 被跳过且计数不虚报。"""
    result = add_module.add_field(
        [{"name": "e", "normalize": [], "parser": {"filter": []}}], "f", "v"
    )
    assert result["status"] == "success"
    assert "跳过 1" in result["message"]
    assert "成功为 0" in result["message"]


def test删除字段保护日志类型等保留字段(delete_module):
    """original_log / rule_name_list / 日志类型 均不可删除。"""
    for field_name in ("original_log", "rule_name_list", "日志类型"):
        result = delete_module.delete_field(_sample_entities(), [field_name])
        assert result["status"] == "error"
        assert "保留字段" in result["message"]


def test删除字段移除normalize并合并removeFields(delete_module):
    """第二次删除合并进已有 removeFields，normalize 同步移除。"""
    once = delete_module.delete_field(_sample_entities(), ["a"])
    twice = delete_module.delete_field(once["data"], ["b"])
    assert twice["status"] == "success"
    filters = twice["data"][0]["parser"]["filter"]
    remove_filters = [f for f in filters if f["name"] == "removeFields"]
    assert len(remove_filters) == 1
    assert remove_filters[0]["fields"] == ["a", "b"]
    entry_indexes = {item["index"] for item in twice["data"][0]["normalize"]}
    sub_indexes = {item["index"] for item in twice["data"][1]["normalize"]}
    assert not entry_indexes & {"a", "b"}
    assert not sub_indexes & {"a", "b"}
    assert "original_log" in sub_indexes  # 保留字段不受删除影响


def test合并字段生成merger与预览条目(merge_module):
    """merger filter 结构与 normalize 预览拼接正确。"""
    result = merge_module.merge_fields(_sample_entities(), ["a", "b"], "d", "-")
    assert result["status"] == "success"
    merger = result["data"][0]["parser"]["filter"][0]
    assert merger == {
        "name": "merger",
        "field": "d",
        "sep": "-",
        "id": "",
        "fields": ["a", "b"],
    }
    assert result["data"][0]["normalize"][-1]["index"] == "d"
    assert result["data"][0]["normalize"][-1]["result"] == ["1-2"]


def test合并字段源缺失时列出可用字段(merge_module):
    """所有 entity 都缺同一源字段返回 error 并列并集词表（#147 per-entity）。"""
    result = merge_module.merge_fields(_sample_entities(), ["a", "missing"], "d", "")
    assert result["status"] == "error"
    assert "missing" in result["message"]
    assert "不存在于任何（目标）子规则" in result["message"]


# ---------------------------------------------------------------------------
# 类型化契约 seam
# ---------------------------------------------------------------------------


def test契约引用型值必须是占位格式():
    """value_type=reference 时值必须形如 %{index}。"""
    with pytest.raises(Exception):
        AddFieldsStep(
            step_id="s1",
            type="add_fields",
            field_name="x",
            field_value="notref",
            value_type="reference",
            config_ref="session.decoded_config",
        )


def test契约合并步骤至少两个源字段():
    """source_fields 少于 2 个被 pydantic 拒绝。"""
    with pytest.raises(Exception):
        MergeFieldsStep(
            step_id="s2",
            type="merge_fields",
            source_fields=("a",),
            target_field="d",
            config_ref="session.mapped_sub_rules",
        )


def test契约三类新步骤进入判别联合():
    """PlanDecision 接受三类新步骤并完成依赖校验。"""
    decision = PlanDecision(
        decision="execute",
        plan_id="p1",
        steps=(
            AddFieldsStep(
                step_id="a1",
                type="add_fields",
                field_name="主机ip",
                field_value="1.1.1.1",
                config_ref="session.decoded_config",
            ),
            DeleteFieldsStep(
                step_id="d1",
                type="delete_fields",
                fields=("a", "b"),
                config_ref="session.mapped_sub_rules",
                depends_on=("a1",),
            ),
            MergeFieldsStep(
                step_id="m1",
                type="merge_fields",
                source_fields=("a", "b"),
                target_field="d",
                sep="-",
                config_ref="session.mapped_sub_rules",
                depends_on=("d1",),
            ),
        ),
    )
    assert [step.type for step in decision.steps] == [
        "add_fields",
        "delete_fields",
        "merge_fields",
    ]


# ---------------------------------------------------------------------------
# FieldSkillAdapter seam
# ---------------------------------------------------------------------------


def test注册表脚本均存在且适配器表包含新类型():
    """注册表条目指向真实脚本；默认适配器表按类型注册。"""
    from application.adapters import create_default_adapters

    for step_type, (script_rel, function_name) in FIELD_SKILL_REGISTRY.items():
        assert (_REPO_ROOT / script_rel).is_file(), script_rel
        assert callable(_load_skill_function(step_type))
        assert getattr(_load_skill_function(step_type), "__name__") == function_name
    table = create_default_adapters(team=None)
    for step_type in FIELD_SKILL_REGISTRY:
        assert step_type in table


def _run(adapter, step, session):
    return asyncio.run(adapter.execute(step, _context(session), {}))


def test适配器添加字段写回session并产出下载产物():
    """add_fields 成功：session 同字段更新，产物 base64 可解回。"""
    session = {"decoded_data": _sample_entities()}
    step = AddFieldsStep(
        step_id="a1",
        type="add_fields",
        field_name="主机ip",
        field_value="1.1.1.1",
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.SUCCESS
    assert result.artifact.download_kind == "field_adjusted_config"
    decoded = json.loads(base64.b64decode(result.artifact.content))
    assert decoded[0]["parser"]["filter"][0]["fields"] == {"主机ip": "1.1.1.1"}
    assert session["decoded_data"][0]["normalize"][-1]["index"] == "主机ip"


def test适配器缺配置返回config_required():
    """session 无配置时快速失败，不读其他来源兜底。"""
    step = AddFieldsStep(
        step_id="a1",
        type="add_fields",
        field_name="x",
        field_value="1",
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, {"decoded_data": _sample_entities()})
    assert result.status == StepStatus.FAILED
    assert result.error_code == "config_required"


def test适配器合并源缺失映射field_not_found():
    """skill 脚本错误消息映射为稳定错误码。"""
    session = {"decoded_data": _sample_entities()}
    step = MergeFieldsStep(
        step_id="m1",
        type="merge_fields",
        source_fields=("a", "missing"),
        target_field="d",
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.FAILED
    assert result.error_code == "field_not_found"


def test适配器删除字段作用于子规则并拒绝未找到字段():
    """delete_fields 对 mapped_sub_rules 生效；不存在的字段被前置拒绝（#146）。"""
    session = {"mapped_sub_rules": _sample_entities()}
    step = DeleteFieldsStep(
        step_id="d1",
        type="delete_fields",
        fields=("a",),
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.SUCCESS
    indexes = {item["index"] for item in session["mapped_sub_rules"][0]["normalize"]}
    assert "a" not in indexes

    # 混入不存在的字段：适配器在词汇解析层拒绝并列出对照表（#146 新语义）
    session2 = {"mapped_sub_rules": _sample_entities()}
    step2 = DeleteFieldsStep(
        step_id="d2",
        type="delete_fields",
        fields=("a", "nope"),
        config_ref="session.mapped_sub_rules",
    )
    result2 = _run(FieldSkillAdapter(), step2, session2)
    assert result2.status == StepStatus.FAILED
    assert result2.error_code == "field_not_found"
    assert "nope" in result2.message
    indexes2 = {item["index"] for item in session2["mapped_sub_rules"][0]["normalize"]}
    assert "a" in indexes2  # 拒绝时不做部分删除


def test适配器删除保留字段返回reserved_field_rejected():
    """保留字段拦截透传为稳定错误码。"""
    session = {"mapped_sub_rules": _sample_entities()}
    step = DeleteFieldsStep(
        step_id="d1",
        type="delete_fields",
        fields=("日志类型",),
        config_ref="session.mapped_sub_rules",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.FAILED
    assert result.error_code == "reserved_field_rejected"


def test适配器事件名称非法值被白名单拒绝():
    """非法分类名返回 invalid_event_name 并列出合法值。"""
    session = {"decoded_data": _sample_entities()}
    step = AddFieldsStep(
        step_id="a1",
        type="add_fields",
        field_name="事件名称",
        field_value="自创类别",
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.FAILED
    assert result.error_code == "invalid_event_name"
    assert "网络攻击" in result.message
    assert "登录事件" in result.message


def test适配器事件名称不支持引用型值():
    """引用型事件名称直接拒绝。"""
    step = AddFieldsStep(
        step_id="a1",
        type="add_fields",
        field_name="事件名称",
        field_value="%{a}",
        value_type="reference",
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, {"decoded_data": _sample_entities()})
    assert result.status == StepStatus.FAILED
    assert result.error_code == "invalid_event_name"


@pytest.mark.parametrize(
    "event_name,expected_level",
    [("网络攻击", "提醒"), ("其他告警", "提醒"), ("登录事件", "信息"), ("web访问", "信息")],
)
def test适配器事件名称自动联动绑定级别(event_name, expected_level):
    """合法事件名称添加后，事件级别按绑定表自动写入。"""
    session = {"decoded_data": _sample_entities()}
    step = AddFieldsStep(
        step_id="a1",
        type="add_fields",
        field_name="事件名称",
        field_value=event_name,
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.SUCCESS
    assert expected_level in result.message
    fields_written = {}
    for entity in session["decoded_data"]:
        for filter_item in entity["parser"]["filter"]:
            if filter_item.get("name") == "addFields" and filter_item.get("id") == "":
                fields_written.update(filter_item.get("fields", {}))
    assert fields_written["事件名称"] == event_name
    assert fields_written["事件级别"] == expected_level


def test适配器事件级别已存在时阻止联动写入():
    """事件级别已存在时返回 event_level_conflict，提示先删除再改。"""
    entities = _sample_entities()
    entities[0]["normalize"].append({"index": "事件级别", "result": ["低危"]})
    session = {"decoded_data": entities}
    step = AddFieldsStep(
        step_id="a1",
        type="add_fields",
        field_name="事件名称",
        field_value="网络攻击",
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.FAILED
    assert result.error_code == "event_level_conflict"
