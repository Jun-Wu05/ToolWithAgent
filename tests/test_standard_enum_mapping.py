"""#189 标准字段映射自动补全枚举值：36 个验收场景的聚焦测试（全离线假件）。

分组：目录与策略（1-4）、提取与隔离（5-13）、字段判断（14-20）、
模型输出校验（21-29）、写回与回归（30-36）。
"""

from __future__ import annotations

import asyncio
import json

from application.execution import ExecutionContext
from application.session_projection import build_session_facts
from application.standard_enum_mapping import (
    FieldValueProfile,
    build_review_prompt,
    build_value_profiles_from_config,
    build_value_profiles_from_logs,
    review_enum_profile,
)
from agent.shared.mapping_utils import apply_enum_outcomes
from contracts.planner_models import FieldMappingStep, StepStatus
from contracts.session_facts import SessionFacts

from factories import make_session_state

POLICY_RESULT_WHITELIST = ("失败", "成功", "未知")


def _policies():
    from agent.core.standard_field_catalog import enum_auto_mapping_policies

    return enum_auto_mapping_policies()


def _result_policy():
    return _policies()["事件结果"]


def _kv_rule(name: str, logtype: str, indexes: list[str]) -> dict:
    """构造 KV 子规则：addFields 日志类型过滤 + 指定 index 的 normalize。"""
    return {
        "name": name,
        "parser": {
            "name": "delimitWithKeyMap",
            "tab": "=",
            "delimit": "\\s",
            "filter": [{"name": "addFields", "fields": {"日志类型": logtype}}],
        },
        "normalize": [
            {
                "index": index,
                "mappings": [],
                "field": None,
                "sim": None,
                "result": [],
                "info": None,
                "entity": None,
                "required": False,
                "core": None,
                "value": None,
            }
            for index in indexes
        ],
    }


def _model_reply(rows: list[dict]):
    """构造返回固定映射行的二阶段假件（兼容 call_model 协议）。"""
    async def call_model(prompt: str) -> str:
        return json.dumps(rows, ensure_ascii=False)

    return call_model


# ---------------------------------------------------------------------------
# 组 1：目录与策略（场景 1-4）
# ---------------------------------------------------------------------------

def test场景1_目录仅识别8个自动枚举字段():
    policies = _policies()
    assert len(policies) == 8
    assert all(policy.whitelist for policy in policies.values())


def test场景2_事件动作白名单为放行拦截未知():
    policy = _policies()["事件动作"]
    assert policy.field_name == "event_action"
    assert policy.whitelist == ("放行", "拦截", "未知")


def test场景3_默认值均属于各自白名单():
    for policy in _policies().values():
        assert policy.default_value in policy.whitelist, policy.system_property_name


def test场景4_操作类型与威胁类型明确排除():
    from agent.core.standard_field_catalog import (
        ENUM_AUTO_MAPPING_EXCLUSIONS,
        resolve_enum_field,
    )

    targets = set(_policies())
    assert not targets & set(ENUM_AUTO_MAPPING_EXCLUSIONS)
    assert resolve_enum_field("threat_type") is None
    assert resolve_enum_field("操作类型") is None


# ---------------------------------------------------------------------------
# 组 2：提取与隔离（场景 5-13）
# ---------------------------------------------------------------------------

def test场景5_万行日志5个唯一值全部提取不依赖样本():
    lines = [f"FW logtype=X result=success seq={i}" for i in range(5_000)]
    lines += [f"FW logtype=X result=timeout seq={i}" for i in range(5_000)]
    rule = _kv_rule("X_kv_子规则", "X", ["result"])
    profiles = build_value_profiles_from_logs([rule], lines)
    profile = next(iter(profiles.values()))
    assert profile.status == "ok"
    assert set(profile.values) == {"success", "timeout"}
    assert profile.values["success"] == 5_000
    assert profile.scanned_lines == 10_000


def test场景6_不同日志类型数据严格隔离():
    lines = [
        "AUDIT type=login result=success",
        "IPS type=block result=drop",
    ]
    rules = [
        _kv_rule("AUDIT_kv_子规则", "AUDIT", ["result"]),
        _kv_rule("IPS_kv_子规则", "IPS", ["result"]),
    ]
    profiles = build_value_profiles_from_logs(rules, lines)
    by_owner = {profile.owner: profile for profile in profiles.values()}
    assert set(by_owner["AUDIT_kv_子规则"].values) == {"success"}
    assert set(by_owner["IPS_kv_子规则"].values) == {"drop"}


def test场景7_共有字段在多个日志类型均有画像():
    lines = ["AUDIT result=success", "IPS result=block"]
    rules = [
        _kv_rule("AUDIT_kv_子规则", "AUDIT", ["result"]),
        _kv_rule("IPS_kv_子规则", "IPS", ["result"]),
    ]
    profiles = build_value_profiles_from_logs(rules, lines)
    assert len(profiles) == 2  # 两条子规则各有 (owner, result) 画像


def test场景8_相同原值在不同日志类型保持独立画像():
    lines = ["AUDIT result=0", "IPS result=0"]
    rules = [
        _kv_rule("AUDIT_kv_子规则", "AUDIT", ["result"]),
        _kv_rule("IPS_kv_子规则", "IPS", ["result"]),
    ]
    profiles = build_value_profiles_from_logs(rules, lines)
    owners = {profile.owner for profile in profiles.values()}
    assert owners == {"AUDIT_kv_子规则", "IPS_kv_子规则"}


def test场景9_重复原值正确去重并计数():
    lines = ["AUDIT result=a", "AUDIT result=a", "AUDIT result=b"]
    profiles = build_value_profiles_from_logs(
        [_kv_rule("AUDIT_kv_子规则", "AUDIT", ["result"])], lines
    )
    profile = next(iter(profiles.values()))
    assert profile.values == {"a": 2, "b": 1}


def test场景10_配置样本模式处理并标记来源():
    config = [{"name": "r", "normalize": [{"index": "result", "result": ["success"]}]}]
    profiles = build_value_profiles_from_config(config)
    profile = next(iter(profiles.values()))
    assert profile.source == "config-sample"
    assert set(profile.values) == {"success"}


def test场景11_缺失null空字符串只计数不生成值():
    rule = _kv_rule("R", "AUDIT", ["result", "missing_field"])
    rule["normalize"][0]["result"] = ["success", "", None]
    profiles = build_value_profiles_from_config([rule])
    values = {profile.field: profile for profile in profiles.values()}
    assert values["result"].values == {"success": 1}
    assert values["result"].empty_count == 2


def test场景12_数组或对象导致整画像拒绝():
    config = [{"name": "r", "normalize": [{"index": "result", "result": [["a"]]}]}]
    profile = next(iter(build_value_profiles_from_config(config).values()))
    assert profile.status == "rejected"
    assert "数组或对象" in profile.reject_reason


def test场景13_十个唯一值允许第十一个拒绝不截断():
    ok_lines = [f"AUDIT result=v{i}" for i in range(10)]
    rule = _kv_rule("AUDIT_kv_子规则", "AUDIT", ["result"])
    ok = next(iter(build_value_profiles_from_logs([rule], ok_lines).values()))
    assert ok.status == "ok" and len(ok.values) == 10
    bad_lines = ok_lines + ["AUDIT result=v10"]
    bad = next(iter(build_value_profiles_from_logs([rule], bad_lines).values()))
    assert bad.status == "rejected"
    assert "上限" in bad.reject_reason


# ---------------------------------------------------------------------------
# 组 3：字段判断（场景 14-20）
# ---------------------------------------------------------------------------

class _RecordingRunner:
    """记录收到的字段并按原样返回机械结果的批处理假件。"""

    def __init__(self) -> None:
        self.fields: list[str] = []
        self.value_profiles = None

    async def run(self, fields, **kwargs):
        self.fields = list(fields)
        self.value_profiles = kwargs.get("value_profiles")
        return [
            {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
            for field in fields
        ]


class _EnumReviewMember:
    """按值画像返回合法归类结果的二阶段成员假件。"""

    name = "FieldMappingAgent"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, prompt: str):
        """从二阶段输入解析值列表并全部映射到「成功」。"""
        self.calls.append(prompt)
        values_block = prompt.split("## 唯一非空值", 1)[1].split("## 白名单", 1)[0]
        payload = json.loads(values_block.strip().split("\n", 1)[1])
        return json.dumps(
            [
                {"原始字段名": item["orgValue"], "系统属性名称": "成功", "匹配状态": "匹配成功"}
                for item in payload
            ],
            ensure_ascii=False,
        )


class _Team:
    """最小专业 Agent 注册表假件。"""

    def __init__(self, member) -> None:
        self.members = [member]


def _enum_adapter_session(log_lines: list[str]):
    rule = _kv_rule("AUDIT_kv_子规则", "AUDIT", ["result", "zzz"])
    return make_session_state(
        mapped_sub_rules=[rule],
        raw_log_lines=log_lines,
    )


def _run_enum_adapter(session, runner, team, event_classifier):
    from application.adapters.field_mapping import FieldMappingAdapter

    facts = SessionFacts(
        available_fields=("result", "zzz"),
        mappable_fields=("result", "zzz"),
    )
    return asyncio.run(
        FieldMappingAdapter(
            team=team, batch_runner=runner, event_classifier=event_classifier
        ).execute(
            FieldMappingStep(
                step_id="mapping", type="field_mapping", source_ref="session.fields"
            ),
            ExecutionContext(session=session, session_facts=facts),
            {},
        )
    )


def test场景14_精确英文字段名绕过LLM字段猜测():
    runner = _RecordingRunner()
    session = _enum_adapter_session(["AUDIT result=success zzz=1"])
    result = _run_enum_adapter(
        session, runner, _Team(_EnumReviewMember()), lambda prompt: "[]"
    )
    assert result.status == StepStatus.SUCCESS
    assert runner.fields == ["zzz"]  # result 被确定性摘出，不进 LLM 批次
    rows = {row["原始字段名"]: row for row in session.last_mapping_data}
    assert rows["result"]["系统属性名称"] == "事件结果"
    assert rows["result"]["匹配状态"] == "匹配成功"


def test场景15_已登记同义词确定性命中():
    from agent.core.standard_field_catalog import resolve_enum_field

    assert resolve_enum_field("威胁等级") == ("威胁等级", "synonym")


def test场景16_值画像进入第一阶段输入且默认路径不变():
    from application.field_mapping_input import build_batch_llm_input

    legacy = build_batch_llm_input(
        "执行标准字段映射", "AUDIT result=success", ["zzz"], 1, 1,
        prequery=lambda fields: "",
    )
    profile = FieldValueProfile(
        owner="AUDIT_kv_子规则", field="zzz",
        values={"1": 3}, empty_count=0, scanned_lines=3, hit_lines=3,
    )
    enhanced = build_batch_llm_input(
        "执行标准字段映射", "AUDIT result=success", ["zzz"], 1, 1,
        prequery=lambda fields: "",
        value_profiles={"zzz": [profile]},
    )
    assert "字段值画像" in enhanced
    assert "AUDIT_kv_子规则" in enhanced and "1×3" in enhanced
    assert enhanced.startswith(legacy.split("📋 原始日志样本")[0].rstrip())
    assert legacy == build_batch_llm_input(
        "执行标准字段映射", "AUDIT result=success", ["zzz"], 1, 1,
        prequery=lambda fields: ""
    )


def test场景17_增强候选携带白名单与目录元数据():
    from agent.core.field_retriever import render_candidates_enriched

    table = {"result": [("事件结果", 1.0, "result", "")]}
    rendered = render_candidates_enriched(table, top_k=5)
    assert "事件结果" in rendered and "枚举:失败,成功,未知" in rendered
    assert "对象:" in rendered and "类型:枚举" in rendered


def test场景18_值语义不兼容时按默认值兜底写入():
    """契约调整（不能缺）：未匹配行按默认值落库，不再整画像拒绝。"""
    profile = FieldValueProfile(owner="R", field="result", values={"success": 2, "timeout": 1})
    call_model = _model_reply(
        [
            {"原始字段名": "success", "系统属性名称": "未匹配", "匹配状态": "未匹配"},
            {"原始字段名": "timeout", "系统属性名称": "未知", "匹配状态": "匹配成功"},
        ]
    )
    outcome = asyncio.run(
        review_enum_profile(("R", "result"), profile, _result_policy(), "llm", call_model)
    )
    assert outcome.mappings == (
        {"mappingType": "EQUAL", "orgValue": "success", "mappingValue": "未知"},
        {"mappingType": "EQUAL", "orgValue": "timeout", "mappingValue": "未知"},
    )
    assert not outcome.reject_reason


def test场景19_全部原值落默认值时正常写入():
    """契约调整（不能缺）：删除全默认否决，默认值是合法落库结果。"""
    profile = FieldValueProfile(owner="R", field="result", values={"仅记录": 3})
    outcome = asyncio.run(
        review_enum_profile(
            ("R", "result"), profile, _result_policy(), "llm",
            _model_reply(
                [{"原始字段名": "仅记录", "系统属性名称": "未知", "匹配状态": "匹配成功"}]
            ),
        )
    )
    assert outcome.mappings == (
        {"mappingType": "EQUAL", "orgValue": "仅记录", "mappingValue": "未知"},
    )
    assert outcome.default_mapped_count == 1


def test场景20_一对一占用冲突裁决不回归():
    from application.field_mapping_conflicts import resolve_field_mapping_conflicts

    rows = [
        {"原始字段名": "result", "系统属性名称": "事件结果", "匹配状态": "匹配成功"},
        {"原始字段名": "op_result", "系统属性名称": "事件结果", "匹配状态": "匹配成功"},
    ]

    def retriever(fields):
        return {"result": [("事件结果", 1.0, "result", "")]}

    outcome = resolve_field_mapping_conflicts(rows, candidate_retriever=retriever)
    final = {row["原始字段名"]: row for row in outcome.rows}
    assert final["result"]["匹配状态"] == "匹配成功"
    assert final["op_result"]["匹配状态"] == "未匹配"


# ---------------------------------------------------------------------------
# 组 4：模型输出校验（场景 21-29）
# ---------------------------------------------------------------------------

def _review(rows):
    profile = FieldValueProfile(owner="R", field="result", values={"success": 2, "timeout": 1})
    return asyncio.run(
        review_enum_profile(
            ("R", "result"), profile, _result_policy(), "exact", _model_reply(rows)
        )
    )


def test场景21_全部非空原值均有且仅有一条EQUAL映射():
    outcome = _review(
        [
            {"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"},
            {"原始字段名": "timeout", "系统属性名称": "未知", "匹配状态": "匹配成功"},
        ]
    )
    assert outcome.mappings == (
        {"mappingType": "EQUAL", "orgValue": "success", "mappingValue": "成功"},
        {"mappingType": "EQUAL", "orgValue": "timeout", "mappingValue": "未知"},
    )
    assert outcome.default_mapped_count == 1


def test场景22_缺少任一原值时拒绝():
    outcome = _review(
        [{"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"}]
    )
    assert outcome.mappings == () and "不一致" in outcome.reject_reason


def test场景23_重复orgValue时拒绝():
    outcome = _review(
        [
            {"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"},
            {"原始字段名": "success", "系统属性名称": "未知", "匹配状态": "匹配成功"},
            {"原始字段名": "timeout", "系统属性名称": "未知", "匹配状态": "匹配成功"},
        ]
    )
    assert outcome.mappings == () and "重复" in outcome.reject_reason


def test场景24_幻觉新增orgValue时拒绝():
    outcome = _review(
        [
            {"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"},
            {"原始字段名": "timeout", "系统属性名称": "未知", "匹配状态": "匹配成功"},
            {"原始字段名": "phantom", "系统属性名称": "未知", "匹配状态": "匹配成功"},
        ]
    )
    assert outcome.mappings == () and "不一致" in outcome.reject_reason


def test场景25_orgValue大小写与内部空格逐字保留():
    profile = FieldValueProfile(owner="R", field="result", values={"Success Case": 1, "success": 1})
    outcome = asyncio.run(
        review_enum_profile(
            ("R", "result"), profile, _result_policy(), "llm",
            _model_reply(
                [
                    {"原始字段名": "Success Case", "系统属性名称": "成功", "匹配状态": "匹配成功"},
                    {"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"},
                ]
            ),
        )
    )
    assert {item["orgValue"] for item in outcome.mappings} == {"Success Case", "success"}


def test场景27_白名单外mappingValue拒绝():
    outcome = _review(
        [
            {"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"},
            {"原始字段名": "timeout", "系统属性名称": "非法定值", "匹配状态": "匹配成功"},
        ]
    )
    assert outcome.mappings == () and "白名单" in outcome.reject_reason


def test场景28_非法输出按既有策略重试一次仍失败则局部拒绝():
    calls = []

    async def call_model(prompt: str) -> str:
        calls.append(prompt)
        return "not-json"

    profile = FieldValueProfile(owner="R", field="result", values={"success": 1})
    outcome = asyncio.run(
        review_enum_profile(("R", "result"), profile, _result_policy(), "llm", call_model)
    )
    assert len(calls) == 2
    assert outcome.mappings == () and "调用失败" in outcome.reject_reason


def test场景29_无法归类的兼容值显式映射到默认值():
    outcome = _review(
        [
            {"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"},
            {"原始字段名": "timeout", "系统属性名称": "未知", "匹配状态": "匹配成功"},
        ]
    )
    assert outcome.mappings
    assert outcome.default_mapped_count == 1


def test场景26_二阶段输入包含白名单与逐字值约束():
    profile = FieldValueProfile(owner="R", field="result", values={"success": 2})
    prompt = build_review_prompt(profile, _result_policy())
    assert '"失败"' in prompt and '"成功"' in prompt and '"未知"' in prompt  # 白名单目录注入
    assert '{"orgValue": "success", "count": 2}' in prompt


# ---------------------------------------------------------------------------
# 组 5：写回与回归（场景 30-36）
# ---------------------------------------------------------------------------

def _rules_with_result(mappings=None, field=None, value=None):
    entry = {
        "index": "result", "mappings": mappings or [], "field": field,
        "sim": True, "result": ["success"], "info": None, "entity": "事件",
        "required": False, "core": False, "value": value,
    }
    return [{"name": "R", "normalize": [entry]}]


def _ok_outcome(key=("0", "result")):
    profile = FieldValueProfile(owner="R", field="result", values={"success": 1})
    return asyncio.run(
        review_enum_profile(
            key, profile, _result_policy(), "exact",
            _model_reply(
                [{"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"}]
            ),
        )
    )


def test场景30_写入正确mappings与外层默认值():
    rules = _rules_with_result(field="事件结果")
    written = apply_enum_outcomes(rules, {("0", "result"): _ok_outcome()})
    assert written == 1
    entry = rules[0]["normalize"][0]
    assert entry["mappings"] == [
        {"mappingType": "EQUAL", "orgValue": "success", "mappingValue": "成功"}
    ]
    assert entry["value"] == "未知"


def test场景31_已映射字段不自动补写或覆盖():
    rules = _rules_with_result(
        field="事件结果",
        mappings=[{"mappingType": "EQUAL", "orgValue": "success", "mappingValue": "成功"}],
        value="成功",
    )
    written = apply_enum_outcomes(rules, {(("0",), "result"): _ok_outcome()})
    assert written == 0
    assert rules[0]["normalize"][0]["mappings"] == [
        {"mappingType": "EQUAL", "orgValue": "success", "mappingValue": "成功"}
    ]


def test场景32_已有不明mappings的条目失败关闭():
    rules = _rules_with_result(
        field="事件结果",
        mappings=[{"mappingType": "REGULAR", "orgValue": "x", "mappingValue": "y"}],
    )
    written = apply_enum_outcomes(rules, {(("0",), "result"): _ok_outcome()})
    assert written == 0
    assert rules[0]["normalize"][0]["mappings"] == [
        {"mappingType": "REGULAR", "orgValue": "x", "mappingValue": "y"}
    ]


def test场景33_单个画像失败不影响其他字段映射成功():
    import copy as _copy

    rules = _rules_with_result(field="事件结果")
    rules[0]["normalize"].append(_copy.deepcopy(rules[0]["normalize"][0]))
    rules[0]["normalize"][1]["index"] = "http_method"
    ok = _ok_outcome()
    failed_profile = FieldValueProfile(owner="R", field="http_method", status="rejected",
                                       reject_reason="唯一值超过 10 个上限，拒绝整个画像")
    failed = asyncio.run(
        review_enum_profile(
            ("0", "http_method"), failed_profile,
            _policies()["HTTP请求方法"], "llm", _model_reply([]),
        )
    )
    written = apply_enum_outcomes(rules, {("0", "result"): ok, ("0", "http_method"): failed})
    assert written == 1
    assert rules[0]["normalize"][1]["mappings"] == []


def test场景34_结构性失败画像不产生部分写入():
    rules = _rules_with_result(field="事件结果")
    profile = FieldValueProfile(owner="R", field="result", values={"success": 1})
    outcome = asyncio.run(
        review_enum_profile(
            ("0", "result"), profile, _result_policy(), "llm",
            _model_reply(
                [{"原始字段名": "phantom", "系统属性名称": "成功", "匹配状态": "匹配成功"}]
            ),
        )
    )
    assert apply_enum_outcomes(rules, {("0", "result"): outcome}) == 0
    assert rules[0]["normalize"][0]["mappings"] == []
    assert rules[0]["normalize"][0]["value"] is None


def test场景35_写回保持JSON根结构与键语义():
    rules = _rules_with_result(field="事件结果")
    rules.append({"name": "other", "parser": {"name": "json"}, "normalize": []})
    apply_enum_outcomes(rules, {(("0",), "result"): _ok_outcome()})
    assert [rule["name"] for rule in rules] == ["R", "other"]
    assert set(rules[0]["normalize"][0]) == {
        "index", "mappings", "field", "sim", "result", "info", "entity",
        "required", "core", "value",
    }


def test场景36_重复执行不产生重复mappings():
    rules = _rules_with_result(field="事件结果")
    outcome = _ok_outcome()
    apply_enum_outcomes(rules, {("0", "result"): outcome})
    apply_enum_outcomes(rules, {("0", "result"): _ok_outcome()})
    assert rules[0]["normalize"][0]["mappings"] == [
        {"mappingType": "EQUAL", "orgValue": "success", "mappingValue": "成功"}
    ]


# ---------------------------------------------------------------------------
# 集成：全局降级与成功写入（场景 18/19 的端到端面，2026-09-28 契约调整）
# ---------------------------------------------------------------------------

def test集成_全部画像结构失败时字段全局未匹配():
    class _BrokenMember:
        name = "FieldMappingAgent"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, prompt: str):
            """持续返回非法 JSON，触发调用失败的结构性拒绝。"""
            self.calls.append(prompt)
            return "not-json"

    runner = _RecordingRunner()
    session = _enum_adapter_session(["AUDIT result=success zzz=1"])
    result = _run_enum_adapter(session, runner, _Team(_BrokenMember()), lambda p: "[]")
    assert result.status == StepStatus.SUCCESS
    assert len(runner.fields) == 1  # 只 zzz 进 LLM 批次，result 被 exact 摘出
    entry = {
        item["index"]: item for item in session.mapped_sub_rules[0]["normalize"]
    }
    assert entry["result"]["field"] is None  # 唯一画像结构失败 → 全局未匹配
    assert entry["result"].get("mappings") == []
    assert "未通过结构校验" in result.message


def test集成_二阶段成功时通过FieldMappingAgent写入mappings与默认值():
    runner = _RecordingRunner()
    member = _EnumReviewMember()
    session = _enum_adapter_session(["AUDIT result=success zzz=1"])
    result = _run_enum_adapter(session, runner, _Team(member), lambda p: "[]")
    assert result.status == StepStatus.SUCCESS
    assert member.calls, "第二阶段应通过 FieldMappingAgent 成员调用"
    entry = {
        item["index"]: item for item in session.mapped_sub_rules[0]["normalize"]
    }
    assert entry["result"]["field"] == "事件结果"
    assert entry["result"]["mappings"] == [
        {"mappingType": "EQUAL", "orgValue": "success", "mappingValue": "成功"}
    ]
    assert entry["result"]["value"] == "未知"
    assert "枚举值映射" in result.message


# ---------------------------------------------------------------------------
# 修复回归：纯 JSON 子规则 logtype 恢复与降级（#285 验收发现 scanned=0）
# ---------------------------------------------------------------------------

def _pure_json_rule() -> dict:
    """模拟 generate_sub_rule 对纯 JSON（非 syslog+JSON）的产物：无日志类型元数据。"""
    return {
        "name": "EDR_alert_json_子规则",
        "parser": {"name": "json", "filter": []},
        "normalize": [
            {"index": "result", "mappings": [], "field": None, "sim": None,
             "result": ["已放行"], "info": None, "entity": None,
             "required": False, "core": None, "value": None},
            {"index": "original_log", "mappings": [], "field": "original_log",
             "sim": True, "result": ["{}"], "info": None, "entity": "日志",
             "required": False, "core": False, "value": None},
        ],
    }


_JSON_FI = r'(\{.*?"type":"(\w+)".*?\})'
_JSON_LINES = [
    '{"type":"EDR_alert","result":"已放行"}',
    '{"type":"EDR_alert","result":"已放行"}',
    '{"type":"EDR_alert","result":"仅记录"}',
]


def test修复_纯JSON子规则从classification恢复logtype并全量扫描():
    """logtype 不在 rule 结构里（纯 JSON），应按序号回查 classification_details。"""
    classification = {
        "feature_identifier": _JSON_FI,
        "feature_body_group": 1,
        "feature_value_group": 2,
        "classification_details": [{"logtype": "EDR_alert"}],
    }
    profiles = build_value_profiles_from_logs(
        [_pure_json_rule()], _JSON_LINES, classification
    )
    profile = profiles[("0", "result")]
    assert profile.source == "full-logs"
    assert profile.scanned_lines == 3
    assert profile.values == {"已放行": 2, "仅记录": 1}


def test修复_logtype彻底不可得时降级configsample():
    """无 classification_details 可回查时降级 config-sample，不再产出静默空画像。"""
    classification = {
        "feature_identifier": _JSON_FI,
        "feature_body_group": 1,
        "feature_value_group": 2,
    }
    profiles = build_value_profiles_from_logs(
        [_pure_json_rule()], _JSON_LINES, classification
    )
    profile = profiles[("0", "result")]
    assert profile.source == "config-sample"
    assert profile.values == {"已放行": 1}
    assert profile.scanned_lines == 1


def test修复_严格匹配零命中时降级configsample():
    """logtype 存在但没有任何行归属时，降级 config-sample 而非空画像。"""
    classification = {
        "feature_identifier": _JSON_FI,
        "feature_body_group": 1,
        "feature_value_group": 2,
        "classification_details": [{"logtype": "OTHER_type"}],
    }
    profiles = build_value_profiles_from_logs(
        [_pure_json_rule()], _JSON_LINES, classification
    )
    profile = profiles[("0", "result")]
    assert profile.source == "config-sample"
    assert profile.values == {"已放行": 1}


def test修复_syslogJSON路径不回归():
    """syslog+JSON 的 addFields 日志类型仍在 rule 内，继续走严格行归属。"""
    rule = _pure_json_rule()
    rule["parser"]["filter"] = [{"name": "addFields", "fields": {"日志类型": "IPS"}}]
    classification = {
        "feature_identifier": _JSON_FI,
        "feature_body_group": 1,
        "feature_value_group": 2,
        "classification_details": [{"logtype": "IPS"}],
    }
    lines = [
        '<134>Sep 24 10:00:00 host app: {"type":"IPS","result":"block"}',
        '<134>Sep 24 10:00:01 host app: {"type":"IPS","result":"block"}',
        '<134>Sep 24 10:00:02 host app: {"type":"IPS","result":"pass"}',
    ]
    profiles = build_value_profiles_from_logs([rule], lines, classification)
    profile = profiles[("0", "result")]
    assert profile.source == "full-logs"
    assert profile.values == {"block": 2, "pass": 1}


# ---------------------------------------------------------------------------
# 契约调整（2026-09-28）：不能缺 + 跨子规则字段一致性 + 数值不猜测
# ---------------------------------------------------------------------------

def test契约_数值语义不明时按默认值落库():
    """0/1 等数值画像：模型按禁猜测指令归默认值 → 正常写入，不缺映射。"""
    profile = FieldValueProfile(owner="R", field="result", values={"0": 5, "1": 3})
    outcome = asyncio.run(
        review_enum_profile(
            ("R", "result"), profile, _result_policy(), "llm",
            _model_reply(
                [
                    {"原始字段名": "0", "系统属性名称": "未知", "匹配状态": "匹配成功"},
                    {"原始字段名": "1", "系统属性名称": "未知", "匹配状态": "匹配成功"},
                ]
            ),
        )
    )
    assert outcome.mappings == (
        {"mappingType": "EQUAL", "orgValue": "0", "mappingValue": "未知"},
        {"mappingType": "EQUAL", "orgValue": "1", "mappingValue": "未知"},
    )
    assert outcome.default_mapped_count == 2


def test契约_空画像不算失败不参与全局降级():
    """无值画像：不调用模型、无 mappings、无拒绝原因（field 照写）。"""
    profile = FieldValueProfile(owner="R", field="result")
    outcome = asyncio.run(
        review_enum_profile(
            ("R", "result"), profile, _result_policy(), "llm", _model_reply([])
        )
    )
    assert outcome.mappings == ()
    assert not outcome.reject_reason


def test契约_跨子规则字段一致性_A成功B结构失败():
    """A 画像成功、B 结构性失败：字段行保持匹配成功，两子规则都写 field。"""
    from application.standard_enum_mapping import run_enum_review_stage

    rows = [{"原始字段名": "result", "系统属性名称": "事件结果", "匹配状态": "匹配成功"}]
    profiles_sub = {
        ("0", "result"): FieldValueProfile(
            owner="A_子规则", field="result", values={"success": 1}
        ),
        ("1", "result"): FieldValueProfile(
            owner="B_子规则", field="result",
            values={f"v{index}": 1 for index in range(11)},
            status="rejected", reject_reason="唯一值超过 10 个上限，拒绝整个画像",
        ),
    }

    async def call_model(prompt: str) -> str:
        """只为 A 画像服务（B 已在画像层拒绝，不会调用）。"""
        return json.dumps(
            [{"原始字段名": "success", "系统属性名称": "成功", "匹配状态": "匹配成功"}],
            ensure_ascii=False,
        )

    outcomes_sub, outcomes_config = asyncio.run(
        run_enum_review_stage(
            rows,
            profiles_sub=profiles_sub,
            profiles_config={},
            resolved_enum_fields={"result": ("事件结果", "exact")},
            call_model=call_model,
        )
    )
    assert rows[0]["匹配状态"] == "匹配成功"  # 存在成功 → 不全局降级
    assert outcomes_sub[("0", "result")].mappings
    assert outcomes_sub[("1", "result")].reject_reason


def test契约_全部结构失败时字段全局未匹配():
    """字段的所有画像都结构性失败 → 全局行降级未匹配（高基数诚实拒绝）。"""
    from application.standard_enum_mapping import run_enum_review_stage

    rows = [{"原始字段名": "result", "系统属性名称": "事件结果", "匹配状态": "匹配成功"}]
    profiles_sub = {
        ("0", "result"): FieldValueProfile(
            owner="A_子规则", field="result",
            values={f"v{index}": 1 for index in range(12)},
            status="rejected", reject_reason="唯一值超过 10 个上限，拒绝整个画像",
        ),
    }
    outcomes_sub, _ = asyncio.run(
        run_enum_review_stage(
            rows,
            profiles_sub=profiles_sub,
            profiles_config={},
            resolved_enum_fields={"result": ("事件结果", "exact")},
            call_model=_model_reply([]),
        )
    )
    assert rows[0]["系统属性名称"] == "未匹配"
    assert rows[0]["匹配状态"] == "未匹配"
    assert outcomes_sub[("0", "result")].reject_reason


def test_public_rule_reader_preserves_missing_json_scan_counts():
    from application.standard_enum_mapping import build_value_profiles_from_logs
    rules=[{'name':'a','parser':{'name':'json'},'normalize':[{'index':'v','result':[]}]}]
    classification={'feature_identifier':r'(.*"kind":"(a)".*)', 'classification_details':[{'logtype':'a'}]}
    profiles=build_value_profiles_from_logs(rules,['{"kind":"a","v":"x"}','{"kind":"a"}','{"kind":"a","v":""}'],classification)
    profile=profiles[('0','v')]
    assert (profile.scanned_lines,profile.hit_lines,profile.empty_count)==(3,2,1)


def test_public_rule_reader_preserves_duplicate_config_entry_and_none_details():
    from application.standard_enum_mapping import build_value_profiles_from_logs
    rules=[{'name':'a','parser':{'name':'json'},'normalize':[{'index':'v','result':['first']},{'index':'v','result':['last']}]}]
    profile=build_value_profiles_from_logs(rules,[],{'classification_details':None})[('0','v')]
    assert profile.source=='config-sample'
    assert profile.values=={'last':1}
