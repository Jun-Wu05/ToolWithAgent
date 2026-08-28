"""事件名称判定与写入测试（PRD #124）。

覆盖：
- 常量与绑定查表（21 枚举、威胁→提醒 / 非威胁→信息）
- classify_sub_rule_events（假 LLM：白名单校验、group 一致性、重试、待人工确认）
- apply_event_fields_to_sub_rules（filter/normalize 结构、深拷贝、未判定不动）
- FieldMappingAdapter 挂接（注入假件成功标注、LLM 失败重试与整步失败、空判定短路）
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent.shared import event_classify
from agent.shared.event_classify import (
    ALL_EVENT_NAMES,
    EVENT_NAME_LEVEL_BINDING,
    NON_THREAT_EVENT_NAMES,
    THREAT_EVENT_NAMES,
    apply_event_fields_to_sub_rules,
    classify_sub_rule_events,
)
from contracts.planner_models import FieldMappingStep
from application.session_projection import build_session_facts
from web.plan_executor import ExecutionContext
from web.adapters.field_mapping import FieldMappingAdapter


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _sub_rules():
    """最小子规则样本：含日志类型条目与样本。"""
    return [
        {
            "name": "暴力破解_kv_子规则",
            "normalize": [
                {"index": "a", "result": ["1"]},
                {"index": "日志类型", "result": ["暴力破解"]},
            ],
            "parser": {"filter": []},
            "sample": "type=暴力破解 src=1.1.1.1 action=block",
        },
        {
            "name": "用户登录_json_子规则",
            "normalize": [
                {"index": "user", "result": ["u1"]},
                {"index": "日志类型", "result": ["登录"]},
            ],
            "parser": {"filter": []},
            "sample": '{"user":"u1","login_result":"success"}',
        },
    ]


def _llm_json(results):
    """构造 LLM 响应文本。"""

    def _call(prompt: str) -> str:
        return json.dumps({"results": results}, ensure_ascii=False)

    return _call


# ---------------------------------------------------------------------------
# 常量与绑定查表
# ---------------------------------------------------------------------------


def test常量覆盖21个枚举值且绑定穷尽():
    """6 威胁 + 15 非威胁 = 21；每个值都有绑定级别。"""
    assert len(THREAT_EVENT_NAMES) == 6
    assert len(NON_THREAT_EVENT_NAMES) == 15
    assert len(ALL_EVENT_NAMES) == 21
    assert set(EVENT_NAME_LEVEL_BINDING) == ALL_EVENT_NAMES
    for name in THREAT_EVENT_NAMES:
        assert EVENT_NAME_LEVEL_BINDING[name] == "提醒"
    for name in NON_THREAT_EVENT_NAMES:
        assert EVENT_NAME_LEVEL_BINDING[name] == "信息"


def test判定知识提示词文件存在且包含合法值清单():
    """提示词是判定的必要条件，缺失即失败；内容覆盖两组值。"""
    prompt_path = _REPO_ROOT / "agent" / "prompts" / "event_classify.md"
    assert prompt_path.is_file()
    content = prompt_path.read_text(encoding="utf-8")
    for name in ALL_EVENT_NAMES:
        assert name in content, name
    assert "dns查询" in content and "dns响应" in content


# ---------------------------------------------------------------------------
# classify_sub_rule_events（注入假 LLM，经 conftest 守卫透传真实实现）
# ---------------------------------------------------------------------------


def test合法输出被接受并返回判定表():
    """合法分类名 + 一致 group 全部接受。"""
    rules = _sub_rules()
    fake = _llm_json(
        [
            {
                "rule_name": "暴力破解_kv_子规则",
                "event_name": "网络攻击",
                "group": "threat",
                "reason": "攻击行为与 block 动作",
            },
            {
                "rule_name": "用户登录_json_子规则",
                "event_name": "登录事件",
                "group": "non_threat",
                "reason": "登录认证行为",
            },
        ]
    )
    judgments, uncertain = asyncio.run(classify_sub_rule_events(rules, llm_client=fake))
    assert judgments == {
        "暴力破解_kv_子规则": "网络攻击",
        "用户登录_json_子规则": "登录事件",
    }
    assert uncertain == []


def test非法值重试后进入待人工确认():
    """第一次输出非法值、第二次仍非法 → 宁缺勿错，不写入。"""
    rules = _sub_rules()
    calls = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(
            {
                "results": [
                    {
                        "rule_name": "暴力破解_kv_子规则",
                        "event_name": "自创威胁类别",
                        "group": "threat",
                        "reason": "x",
                    }
                ]
            },
            ensure_ascii=False,
        )

    judgments, uncertain = asyncio.run(classify_sub_rule_events(rules, llm_client=fake))
    assert len(calls) == 2  # 重试一次
    assert "自创威胁类别" in calls[1]  # 重试带错误反馈
    assert judgments == {}
    assert uncertain == ["暴力破解_kv_子规则", "用户登录_json_子规则"]


def test非法值重试后修正被接受():
    """第一次非法、第二次修正 → 修正值生效。"""
    rules = _sub_rules()
    state = {"count": 0}

    def fake(prompt: str) -> str:
        state["count"] += 1
        event_name = "SQL注入攻击" if state["count"] == 1 else "网络攻击"
        return json.dumps(
            {
                "results": [
                    {
                        "rule_name": "暴力破解_kv_子规则",
                        "event_name": event_name,
                        "group": "threat",
                        "reason": "x",
                    },
                    {
                        "rule_name": "用户登录_json_子规则",
                        "event_name": "登录事件",
                        "group": "non_threat",
                        "reason": "y",
                    },
                ]
            },
            ensure_ascii=False,
        )

    judgments, uncertain = asyncio.run(classify_sub_rule_events(rules, llm_client=fake))
    assert judgments["暴力破解_kv_子规则"] == "网络攻击"
    assert uncertain == []


def test分组不一致被拒绝():
    """event_name 与 group 所属组不一致 → 该条非法。"""
    rules = _sub_rules()
    fake = _llm_json(
        [
            {
                "rule_name": "用户登录_json_子规则",
                "event_name": "登录事件",
                "group": "threat",
                "reason": "标错组",
            }
        ]
    )
    judgments, uncertain = asyncio.run(classify_sub_rule_events(rules, llm_client=fake))
    assert judgments == {}
    assert "用户登录_json_子规则" in uncertain


def test未知规则名被拒绝():
    """LLM 编造的 rule_name 不进入判定表。"""
    rules = _sub_rules()
    fake = _llm_json(
        [
            {
                "rule_name": "不存在的规则",
                "event_name": "网络攻击",
                "group": "threat",
                "reason": "x",
            }
        ]
    )
    judgments, uncertain = asyncio.run(classify_sub_rule_events(rules, llm_client=fake))
    assert judgments == {}
    assert uncertain == ["暴力破解_kv_子规则", "用户登录_json_子规则"]


# ---------------------------------------------------------------------------
# apply_event_fields_to_sub_rules
# ---------------------------------------------------------------------------


def test写入filter与normalize结构并与日志类型同构():
    """addFields 追加在 filter 末尾；normalize 追加两条目，形态仿日志类型条目。"""
    rules = _sub_rules()
    out = apply_event_fields_to_sub_rules(rules, {"暴力破解_kv_子规则": "网络攻击"})
    rule = out[0]
    assert rule["parser"]["filter"] == [
        {
            "fields": {"事件名称": "网络攻击", "事件级别": "提醒"},
            "name": "addFields",
            "id": "",
        }
    ]
    name_entry, level_entry = rule["normalize"][-2:]
    assert name_entry == {
        "mappings": [],
        "field": "event_name",
        "sim": True,
        "result": ["网络攻击"],
        "info": None,
        "entity": "日志",
        "required": False,
        "core": False,
        "value": "",
        "index": "事件名称",
    }
    assert level_entry["field"] == "event_level"
    assert level_entry["index"] == "事件级别"
    assert level_entry["result"] == ["提醒"]
    # 未判定的子规则不动
    assert out[1]["parser"]["filter"] == []
    assert [e["index"] for e in out[1]["normalize"]] == ["user", "日志类型"]


def test写入不修改原数据():
    """深拷贝：原 sub_rules 保持不变。"""
    rules = _sub_rules()
    apply_event_fields_to_sub_rules(rules, {"暴力破解_kv_子规则": "终端告警"})
    assert rules[0]["parser"]["filter"] == []
    assert len(rules[0]["normalize"]) == 2


def test非法判定值不写入():
    """judgments 中混入非法值时对应子规则跳过。"""
    rules = _sub_rules()
    out = apply_event_fields_to_sub_rules(rules, {"暴力破解_kv_子规则": "不存在类别"})
    assert out[0]["parser"]["filter"] == []


# ---------------------------------------------------------------------------
# FieldMappingAdapter 挂接
# ---------------------------------------------------------------------------


def _annotate(adapter, rules):
    """直接调用标注方法（绕过完整映射流程），兼容三元组返回。"""
    step = FieldMappingStep(
        step_id="mapping", type="field_mapping", source_ref="session.fields"
    )
    context = ExecutionContext(session={}, session_facts=build_session_facts({}), progress_sink=None)
    outcome = asyncio.run(adapter._annotate_event_names(step, context, rules))
    return step, outcome


def test挂接注入假件成功标注并返回摘要():
    """构造注入的 event_classifier 假件走真实判定逻辑，返回摘要。"""
    fake = _llm_json(
        [
            {
                "rule_name": "暴力破解_kv_子规则",
                "event_name": "网络攻击",
                "group": "threat",
                "reason": "x",
            },
            {
                "rule_name": "用户登录_json_子规则",
                "event_name": "登录事件",
                "group": "non_threat",
                "reason": "y",
            },
        ]
    )
    adapter = FieldMappingAdapter(team=None, event_classifier=fake)
    step, outcome = _annotate(adapter, _sub_rules())
    annotated, summary, rows = outcome
    assert isinstance(annotated, list)
    assert "事件名称已标注 2 条" in summary
    assert "威胁 1" in summary and "非威胁 1" in summary
    assert annotated[0]["parser"]["filter"][0]["fields"]["事件名称"] == "网络攻击"
    assert len(rows) == 2


def test挂接空判定短路不改数据():
    """无判定时返回原列表与空摘要（conftest 默认守卫即此路径）。"""
    adapter = FieldMappingAdapter(team=None)
    rules = _sub_rules()
    step, outcome = _annotate(adapter, rules)
    annotated, summary, rows = outcome
    assert annotated is rules
    assert not summary


def test挂接llm不可重试错误整步失败(monkeypatch):
    """非可重试异常：不重试，直接 event_classify_failed。"""
    calls = []

    def broken(prompt: str) -> str:
        calls.append(prompt)
        raise RuntimeError("boom")

    adapter = FieldMappingAdapter(team=None, event_classifier=broken)
    step, outcome = _annotate(adapter, _sub_rules())
    from contracts.planner_models import StepResult

    assert isinstance(outcome, StepResult)
    assert outcome.status.value == "failed"
    assert outcome.error_code == "event_classify_failed"
    assert len(calls) == 1  # 不可重试错误不重试


def test挂接待人工确认计入摘要():
    """部分子规则无法判定时摘要列明待人工确认。"""

    def fake(prompt: str) -> str:
        if "上一次输出" in prompt:
            return json.dumps({"results": []}, ensure_ascii=False)
        return json.dumps(
            {
                "results": [
                    {
                        "rule_name": "用户登录_json_子规则",
                        "event_name": "登录事件",
                        "group": "non_threat",
                        "reason": "y",
                    }
                ]
            },
            ensure_ascii=False,
        )

    adapter = FieldMappingAdapter(team=None, event_classifier=fake)
    step, outcome = _annotate(adapter, _sub_rules())
    annotated, summary, rows = outcome
    assert "待人工确认 1 条" in summary
    assert "暴力破解_kv_子规则" in summary
    # 待确认子规则未被写入事件字段
    brute = next(r for r in annotated if r["name"] == "暴力破解_kv_子规则")
    assert brute["parser"]["filter"] == []
    uncertain_rows = [row for row in rows if row.status == "uncertain"]
    assert len(uncertain_rows) == 1
    assert uncertain_rows[0].rule_name == "暴力破解_kv_子规则"
