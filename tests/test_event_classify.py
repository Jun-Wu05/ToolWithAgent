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
    EVENT_LEVEL_CODE_BINDING,
    EVENT_NAME_OPERATION_ENUM_BINDING,
    EVENT_NAME_LEVEL_BINDING,
    NON_THREAT_EVENT_NAMES,
    THREAT_EVENT_NAMES,
    apply_event_fields_to_sub_rules,
    classify_sub_rule_events,
)
from contracts.planner_models import FieldMappingStep
from application.session_projection import build_session_facts
from application.execution import ExecutionContext
from application.adapters.field_mapping import FieldMappingAdapter
from factories import make_session_state


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


def test级别码表覆盖五档且包含绑定表全部产出():
    """#392：显示级→整型码值；绑定表产出的每个级别都必须有码。"""
    assert EVENT_LEVEL_CODE_BINDING == {
        "信息": "0",
        "提醒": "1",
        "警告": "2",
        "严重": "3",
        "紧急": "4",
    }
    assert set(EVENT_NAME_LEVEL_BINDING.values()) <= set(EVENT_LEVEL_CODE_BINDING)


def test判定知识提示词文件存在且包含合法值清单():
    """提示词是判定的必要条件，缺失即失败；内容覆盖两组值。"""
    prompt_path = _REPO_ROOT / "agent" / "prompts" / "event_classify.md"
    assert prompt_path.is_file()
    content = prompt_path.read_text(encoding="utf-8")
    for name in ALL_EVENT_NAMES:
        assert name in content, name
    assert "dns查询" in content and "dns响应" in content
    # #395：输出契约含 operation_type
    assert '"operation_type"' in content


def test操作类型绑定表钉桩七类枚举():
    """#395：仅提示词定义了操作类型枚举的 7 个非威胁类参与绑定。"""
    assert EVENT_NAME_OPERATION_ENUM_BINDING == {
        "登录事件": ("登录", "登出", "其他", "未映射"),
        "审计事件": (
            "其他", "打印审计", "数据库审计", "登出", "登录",
            "移动存储审计", "终端入网", "访客入网", "超时", "远程桌面",
        ),
        "会话操作": ("其他", "开始", "未映射", "终止"),
        "进程操作": (
            "API调用", "其他", "其他属性修改", "创建", "唤醒", "快照",
            "挂起", "未映射", "权限提升", "注入", "篡改", "终止", "访问",
        ),
        "用户操作": (
            "修改", "其他", "其他属性修改", "切换", "创建", "删除", "密码修改",
            "所属组修改", "未映射", "权限修改", "枚举", "激活", "登出", "登录",
            "禁用", "解锁", "重命名", "锁定",
        ),
        "资源监控": ("其他", "故障", "未映射", "正常", "警告"),
        "邮件操作": ("其他", "删除", "发送", "接收", "未映射", "附件下载"),
    }
    assert set(EVENT_NAME_OPERATION_ENUM_BINDING) <= set(NON_THREAT_EVENT_NAMES)


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
    judgments, _operations, uncertain = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake)
    )
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

    judgments, _operations, uncertain = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake)
    )
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

    judgments, _operations, uncertain = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake)
    )
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
    judgments, _operations, uncertain = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake)
    )
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
    judgments, _operations, uncertain = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake)
    )
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
        "mappings": [
            {"mappingType": "EQUAL", "mappingValue": "网络攻击", "orgValue": "网络攻击"}
        ],
        "field": "event_name",
        "sim": True,
        "result": ["网络攻击"],
        "info": None,
        "entity": "事件",
        "required": False,
        "core": False,
        "value": "网络攻击",
        "index": "事件名称",
    }
    assert level_entry["field"] == "event_level"
    assert level_entry["index"] == "事件级别"
    assert level_entry["result"] == ["提醒"]
    assert level_entry["entity"] == "事件"  # 目录对象（#177，原「日志」非法）
    # #392：事件级别整型码值——mappings 记录显示级→码值，value 写码值
    assert level_entry["mappings"] == [
        {"mappingType": "EQUAL", "mappingValue": "1", "orgValue": "提醒"}
    ]
    assert level_entry["value"] == "1"
    # 未判定的子规则不动
    assert out[1]["parser"]["filter"] == []
    assert [e["index"] for e in out[1]["normalize"]] == ["user", "日志类型"]


def test样本数按既有条目result长度推导():
    """#392：result 每份日志一条——既有条目 result 长度即样本数。"""
    rules = [
        {
            "name": "双样本子规则",
            "normalize": [{"index": "a", "result": ["1", "2"]}],
            "parser": {"filter": []},
            "sample": "x\ny",
        },
        {
            "name": "无normalize子规则",
            "normalize": [],
            "parser": {"filter": []},
            "sample": "z",
        },
    ]
    out = apply_event_fields_to_sub_rules(
        rules, {"双样本子规则": "网络攻击", "无normalize子规则": "登录事件"}
    )
    dual_name, dual_level = out[0]["normalize"][-2:]
    assert dual_name["result"] == ["网络攻击", "网络攻击"]
    assert dual_level["result"] == ["提醒", "提醒"]
    fallback_name, fallback_level, fallback_operation = out[1]["normalize"][-3:]
    assert fallback_name["result"] == ["登录事件"]
    assert fallback_level["result"] == ["信息"]
    # 登录事件绑定了操作类型，operations 未传时按「其他」兜底（#395）
    assert fallback_operation["result"] == ["其他"]


def test操作类型判定校验与降级():
    """#395：operation_type 类内白名单校验；非法/缺失降级「其他」；未绑定类不产出。"""
    rules = _sub_rules()
    fake = _llm_json(
        [
            {
                "rule_name": "暴力破解_kv_子规则",
                "event_name": "网络攻击",
                "group": "threat",
                "reason": "攻击行为",
                "operation_type": "登录",  # 威胁组未绑定——忽略
            },
            {
                "rule_name": "用户登录_json_子规则",
                "event_name": "登录事件",
                "group": "non_threat",
                "reason": "登录认证行为",
                "operation_type": "自创操作",  # 非法——降级「其他」
            },
        ]
    )
    judgments, operations, uncertain = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake)
    )
    assert judgments["用户登录_json_子规则"] == "登录事件"
    assert operations == {"用户登录_json_子规则": "其他"}
    assert uncertain == []

    fake_missing = _llm_json(
        [
            {
                "rule_name": "暴力破解_kv_子规则",
                "event_name": "网络攻击",
                "group": "threat",
                "reason": "攻击行为",
            },
            {
                "rule_name": "用户登录_json_子规则",
                "event_name": "登录事件",
                "group": "non_threat",
                "reason": "登录认证行为",
                "operation_type": "登出",
            },
        ]
    )
    _j, operations_valid, _u = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake_missing)
    )
    assert operations_valid == {"用户登录_json_子规则": "登出"}


def test未绑定操作类型的类不写字段():
    """网络连接未定义操作类型枚举——判定输出带 operation 也不写入（#395）。"""
    rules = [
        {
            "name": "流量_kv_子规则",
            "normalize": [{"index": "a", "result": ["1"]}],
            "parser": {"filter": []},
            "sample": "src=1.1.1.1 dst=2.2.2.2",
        }
    ]
    fake = _llm_json(
        [
            {
                "rule_name": "流量_kv_子规则",
                "event_name": "网络连接",
                "group": "non_threat",
                "reason": "纯流量五元组",
                "operation_type": "访问",
            }
        ]
    )
    judgments, operations, _u = asyncio.run(
        classify_sub_rule_events(rules, llm_client=fake)
    )
    assert judgments == {"流量_kv_子规则": "网络连接"}
    assert operations == {}
    out = apply_event_fields_to_sub_rules(rules, judgments, operations)
    rule = out[0]
    assert [e["index"] for e in rule["normalize"][-2:]] == ["事件名称", "事件级别"]
    assert set(rule["parser"]["filter"][-1]["fields"]) == {"事件名称", "事件级别"}


def test写入操作类型条目与addFields():
    """#395：绑定类写第三条目（恒等映射+value+样本数复制），addFields 同步。"""
    rules = [
        {
            "name": "登录_kv_子规则",
            "normalize": [{"index": "a", "result": ["1", "2"]}],
            "parser": {"filter": []},
            "sample": "user=u1 action=login\nuser=u2 action=login",
        }
    ]
    out = apply_event_fields_to_sub_rules(
        rules,
        {"登录_kv_子规则": "登录事件"},
        {"登录_kv_子规则": "登出"},
    )
    rule = out[0]
    assert rule["parser"]["filter"][-1]["fields"] == {
        "事件名称": "登录事件",
        "事件级别": "信息",
        "操作类型": "登出",
    }
    operation_entry = rule["normalize"][-1]
    assert operation_entry == {
        "mappings": [
            {"mappingType": "EQUAL", "mappingValue": "登出", "orgValue": "登出"}
        ],
        "field": "event_operation_type",
        "sim": True,
        "result": ["登出", "登出"],
        "info": None,
        "entity": "事件",
        "required": False,
        "core": False,
        "value": "登出",
        "index": "操作类型",
    }


def test操作类型缺省降级其他():
    """#395：judgments 有值但 operations 缺失时按「其他」兜底写入。"""
    rules = [
        {
            "name": "登录_kv_子规则",
            "normalize": [{"index": "a", "result": ["1"]}],
            "parser": {"filter": []},
            "sample": "user=u1 action=login",
        }
    ]
    out = apply_event_fields_to_sub_rules(rules, {"登录_kv_子规则": "登录事件"})
    operation_entry = out[0]["normalize"][-1]
    assert operation_entry["value"] == "其他"
    assert operation_entry["mappings"] == [
        {"mappingType": "EQUAL", "mappingValue": "其他", "orgValue": "其他"}
    ]
    assert out[0]["parser"]["filter"][-1]["fields"]["操作类型"] == "其他"


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
    session = make_session_state()
    context = ExecutionContext(session=session, session_facts=build_session_facts(session), progress_sink=None)
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
