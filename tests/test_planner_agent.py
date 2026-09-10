"""独立 PlannerAgent 的离线行为测试。"""

import asyncio
import json

import pytest

from application.threat_chain_policy import SourceFieldDecision, build_threat_chain_steps
from contracts.planner_models import ConversationTurn, PlanDecision
from contracts.session_artifacts import ArtifactTargetBinding, ReferenceableArtifactFact
from contracts.session_facts import SessionFacts


async def _bound_threat_fill_runner(_planner_input: str):
    """模拟模型把跨轮威胁填充解析到唯一合法标准字段。"""
    return PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-fill-threat",
            "steps": [
                {
                    "step_id": "fill-1",
                    "type": "fill",
                    "fill_kind": "threat",
                    "target_fields": ["威胁等级"],
                    "source_ref": "session.artifacts.threat_mapping",
                    "config_ref": "session.mapped_sub_rules",
                }
            ],
        }
    )


def _cross_turn_threat_facts(
    available_fields: tuple[str, ...] = (
        "threat_level",
        "威胁等级",
        "protocol",
        "协议",
    ),
) -> SessionFacts:
    """构造 threat_level→威胁等级 的安全产物目录。"""
    return SessionFacts(
        available_config_refs=("session.mapped_sub_rules",),
        available_fields=available_fields,
        referenceable_artifacts=(
            ReferenceableArtifactFact(
                source_ref="session.artifacts.threat_mapping",
                artifact_type="threat_mapping",
                source_field="threat_level",
                item_count=2,
                target_bindings=(
                    ArtifactTargetBinding(
                        config_ref="session.mapped_sub_rules",
                        target_field="威胁等级",
                    ),
                ),
            ),
        ),
    )


async def _threat_chain_runner(_planner_input: str):
    """模拟模型把任意输入都错误规划为完整威胁类型链。"""
    plan = build_threat_chain_steps(
        SourceFieldDecision("alarm_name", 1.0, 1, "test"),
        config_ref="session.mapped_sub_rules",
    )
    return PlanDecision(
        decision="execute",
        plan_id="plan-threat-chain-alarm",
        steps=plan.steps,
    )


async def _threat_intent_runner(planner_input: str):
    """模拟 Agent 对三类威胁意图返回结构化决策。"""
    user_text = json.loads(planner_input)["user_text"]
    if user_text == "把字段值映射为威胁类型":
        return PlanDecision(
            decision="clarification",
            plan_id="missing-source",
            reason_code="threat_source_required",
            question="请明确用于威胁类型映射的来源字段。",
        )
    if user_text.startswith("只做普通字段名映射"):
        return PlanDecision(
            decision="clarification",
            plan_id="excluded-value-mapping",
            reason_code="threat_value_mapping_excluded",
            question="是否执行整批标准字段映射？",
            choices=("执行标准字段映射", "取消"),
        )
    proposal = await _threat_chain_runner(planner_input)
    return proposal.model_copy(
        update={
            "decision": "proposal",
            "reason_code": "confirmation_required",
            "question": "将从 alarm_name 提取枚举值并映射、填充威胁类型，是否执行？",
            "choices": ("确认执行", "取消"),
        }
    )


def test自然语言恰好调用planner一次且返回前不执行业务():
    from agent.core.planner import PlannerService

    calls = []

    async def fake_runner(planner_input: str):
        calls.append(planner_input)
        return PlanDecision.model_validate(
            {
                "decision": "execute",
                "plan_id": "plan-test",
                "steps": [
                    {
                        "step_id": "enum-fill",
                        "type": "fill",
                        "fill_kind": "enum",
                        "target_fields": ["event_type3"],
                        "source_ref": "session.enum_mapping_table",
                        "config_ref": "session.mapped_sub_rules",
                    }
                ],
            }
        )

    planner = PlannerService(runner=fake_runner)
    decision = asyncio.run(planner.plan(
        user_text="枚举值处理",
        conversation_history=[],
        session_facts=SessionFacts(
            has_decoded_config=True,
            has_mapped_sub_rules=True,
            enum_mapping_target_fields=("event_type3",),
        ),
    ))

    assert len(calls) == 1
    assert decision.decision == "execute"
    assert decision.steps[0].type == "fill"


def testPlanner输入只暴露待确认计划摘要():
    from agent.core.planner import build_planner_input
    from contracts.planner_models import PendingPlan

    pending = PendingPlan.model_validate(
        {
            "plan_id": "proposal-secret",
            "session_facts_digest": "a" * 64,
            "steps": [
                {
                    "step_id": "add-1",
                    "type": "add_fields",
                    "field_name": "token",
                    "field_value": "sensitive-value",
                    "config_ref": "session.decoded_config",
                }
            ],
        }
    )

    payload = json.loads(build_planner_input("确认", (), SessionFacts(), pending))

    assert payload["pending_plan"] == {
        "plan_id": "proposal-secret",
        "operations": ["add_fields"],
    }
    assert "sensitive-value" not in json.dumps(payload)


def test威胁来源澄清丢弃模型候选且不倾倒字段池():
    from agent.core.planner import PlannerService

    async def hallucinating_runner(_planner_input: str):
        return PlanDecision(
            decision="clarification",
            plan_id="plan-threat-source",
            reason_code="threat_source_required",
            question="当前可用字段包括 alarm_name、event_str、threat_type。",
            choices=("alarm_name", "event_str", "threat_type"),
        )

    decision = asyncio.run(
        PlannerService(runner=hallucinating_runner).plan(
            user_text="我要进行威胁类型映射",
            conversation_history=(
                ConversationTurn(role="user", content="用 event_str 作为威胁类型来源"),
            ),
            session_facts=SessionFacts(
                threat_source_fields=("alarm_name", "event_type1")
            ),
        )
    )

    assert decision.question == "请明确用于威胁类型映射的来源字段。"
    assert decision.choices == ()


def test自动选择威胁来源不展示完整字段池() -> None:
    """自动选择是执行请求，不应把资格字段池直接倾倒给用户。"""
    from agent.core.planner import PlannerService

    async def runner(_planner_input: str):
        return PlanDecision(
            decision="clarification",
            plan_id="auto-threat-source",
            reason_code="threat_source_required",
            question="placeholder",
            choices=("accuracy", "alarm_name", "event_str"),
        )

    decision = asyncio.run(
        PlannerService(runner=runner).plan(
            user_text="请为威胁类型选择合适的来源字段",
            conversation_history=(),
            session_facts=SessionFacts(
                threat_source_fields=("accuracy", "alarm_name", "event_type1")
            ),
        )
    )

    assert decision.reason_code == "threat_source_auto_requested"
    assert decision.question == "正在从真实字段中自动选择威胁类型来源。"
    assert decision.choices == ()


def test不存在的显式威胁来源返回定向错误() -> None:
    """显式字段不存在时只说明该字段，不回退成完整候选清单。"""
    from agent.core.planner import PlannerService

    async def runner(_planner_input: str):
        return PlanDecision(
            decision="clarification",
            plan_id="missing-threat-source",
            reason_code="threat_source_not_found",
            question="placeholder",
            choices=("alarm_name", "event_type1"),
            parameters={"requested_field": "event_str"},
        )

    decision = asyncio.run(
        PlannerService(runner=runner).plan(
            user_text="用 event_str 作为威胁类型来源",
            conversation_history=(),
            session_facts=SessionFacts(threat_source_fields=("alarm_name",)),
        )
    )

    assert decision.reason_code == "threat_source_not_found"
    assert decision.question == "字段 `event_str` 不存在于当前威胁子规则，未执行。"
    assert decision.choices == ()


@pytest.mark.parametrize(
    ("user_text", "expected_decision", "reason_code"),
    (
        ("把字段值映射为威胁类型", "clarification", "threat_source_required"),
        (
            "只做普通字段名映射，把 alarm_name 映射到威胁类型，不要做值映射",
            "clarification",
            "threat_value_mapping_excluded",
        ),
        (
            "请先给出把 alarm_name 映射为威胁类型的唯一执行方案，等我确认后再执行",
            "proposal",
            "confirmation_required",
        ),
    ),
)
def testAgent判定威胁指令授权边界(
    user_text: str, expected_decision: str, reason_code: str
) -> None:
    """PlannerService透传Agent的结构化澄清或提案决策。"""
    from agent.core.planner import PlannerService

    facts = SessionFacts(
        has_logs=True,
        available_fields=("alarm_name", "event_type1"),
        threat_source_fields=("alarm_name", "event_type1"),
    )
    decision = asyncio.run(
        PlannerService(runner=_threat_intent_runner).plan(
            user_text=user_text,
            conversation_history=(),
            session_facts=facts,
        )
    )
    assert decision.decision == expected_decision
    assert decision.reason_code == reason_code
    assert bool(decision.steps) is (expected_decision == "proposal")


@pytest.mark.parametrize(
    "user_text",
    (
        "把 alarm_name 映射为威胁类型",
        "根据 alarm_name 生成 threat type",
        "将 alarm_name 的值转成威胁类型",
    ),
)
def test威胁指令边界放行明确的值映射请求(user_text: str) -> None:
    """合法来源与值映射意图齐备时不得误拦截。"""
    from agent.core.planner import PlannerService

    facts = SessionFacts(
        has_logs=True,
        available_fields=("alarm_name", "event_type1"),
        threat_source_fields=("alarm_name", "event_type1"),
    )
    decision = asyncio.run(
        PlannerService(runner=_threat_chain_runner).plan(
            user_text=user_text,
            conversation_history=(),
            session_facts=facts,
        )
    )
    assert decision.decision == "execute"


def test跨轮威胁填充不能静默改写用户明确指定的冲突目标():
    """用户指定协议时，即使 Planner 改成合法绑定也必须澄清而非执行。"""
    from agent.core.planner import PlannerService

    decision = asyncio.run(
        PlannerService(runner=_bound_threat_fill_runner).plan(
            user_text="把刚才的威胁映射填入协议",
            conversation_history=[],
            session_facts=_cross_turn_threat_facts(),
        )
    )

    assert decision.decision == "clarification"
    assert decision.reason_code == "artifact_target_mismatch"
    assert decision.steps == ()
    assert "threat_level" in decision.question
    assert "威胁等级" in decision.question
    assert "协议" in decision.question


def test跨轮威胁填充允许自然续接和来源字段对应目标():
    """未点名目标、点名来源字段或唯一标准字段时均保留合法执行计划。"""
    from agent.core.planner import PlannerService

    for user_text in (
        "把刚才的威胁映射填充回去",
        "把刚才的威胁映射填充到对应字段",
        "把刚才的威胁映射写入解析规则",
        "把刚才的威胁映射填入威胁等级",
        "把刚才的威胁映射填入 threat_level",
    ):
        decision = asyncio.run(
            PlannerService(runner=_bound_threat_fill_runner).plan(
                user_text=user_text,
                conversation_history=[],
                session_facts=_cross_turn_threat_facts(),
            )
        )
        assert decision.decision == "execute"
        assert decision.steps[0].target_fields == ("威胁等级",)


def test跨轮威胁填充对配置外显式目标也不能静默改写():
    """用户点名未知字段时应澄清，不能因目录有唯一绑定就替用户改目标。"""
    from agent.core.planner import PlannerService

    decision = asyncio.run(
        PlannerService(runner=_bound_threat_fill_runner).plan(
            user_text="把刚才的威胁映射填入不存在字段",
            conversation_history=[],
            session_facts=_cross_turn_threat_facts(("threat_level", "威胁等级")),
        )
    )

    assert decision.decision == "clarification"
    assert decision.reason_code == "artifact_target_mismatch"
    assert "不存在字段" in decision.question


def testplanner超时时明确记录调用阶段且不做关键词兜底(caplog):
    from agent.core.planner import PlannerService
    import logging

    caplog.set_level(logging.INFO, logger="planner")

    async def unavailable_runner(planner_input: str):
        raise TimeoutError("provider timeout")

    decision = asyncio.run(PlannerService(runner=unavailable_runner).plan(
        user_text="提取 event_type3 的枚举值",
        conversation_history=[],
        session_facts=SessionFacts(has_logs=True, available_fields=("event_type3",)),
    ))

    assert decision.decision == "clarification"
    assert decision.reason_code == "planner_timeout"
    assert decision.steps == ()
    assert "重试" in decision.question
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "[MODEL_CALL_START]" in messages
    assert "[MODEL_CALL_TIMEOUT]" in messages
    assert "provider=" in messages
    assert "model=" in messages
    assert "phase=runner_wait" in messages
    assert "response_received=False" in messages
    assert "elapsed_seconds=" in messages


def testplanner非法输出不会进入执行计划():
    from agent.core.planner import PlannerService

    async def invalid_runner(planner_input: str):
        return {"decision": "execute", "steps": []}

    decision = asyncio.run(PlannerService(runner=invalid_runner).plan(
        user_text="做一下映射",
        conversation_history=[],
        session_facts=SessionFacts(),
    ))

    assert decision.decision == "clarification"
    assert decision.reason_code == "invalid_plan"
    assert decision.steps == ()


def testplanner服务异常记录异常类别而不记录异常原文(caplog):
    """底层服务异常只记录类型和阶段元数据，避免泄露异常原文或用户输入。"""
    from agent.core.planner import PlannerService
    import logging

    caplog.set_level(logging.INFO, logger="planner")

    async def unavailable_runner(_planner_input: str):
        raise RuntimeError("provider-secret-response")

    decision = asyncio.run(
        PlannerService(runner=unavailable_runner).plan(
            user_text="敏感用户指令",
            conversation_history=[],
            session_facts=SessionFacts(),
        )
    )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert decision.reason_code == "planner_unavailable"
    assert "error_type=RuntimeError" in messages
    assert "provider-secret-response" not in messages
    assert "敏感用户指令" not in messages
    assert "phase=runner_wait" in messages
    assert "response_received=False" in messages


def testplanner支持返回协程的同步runner():
    """Agno Agent.arun 是返回协程的普通方法（iscoroutinefunction=False），必须正确 await。

    回归 2026-08-13 线上故障：invoke_runner 曾用 iscoroutinefunction 判定分支，导致 arun
    被当作同步函数调用、协程未被 await，content_kind=coroutine，模型从未真正执行。
    """
    from agent.core.planner import PlannerService

    async def arun_impl(_input):
        return PlanDecision.model_validate(
            {"decision": "clarification", "reason_code": "test", "question": "请补充信息"}
        )

    def arun_like(input):  # 同步函数、返回协程——模拟 Agno Agent.arun
        return arun_impl(input)

    decision = asyncio.run(PlannerService(runner=arun_like).plan(
        user_text="枚举值处理",
        conversation_history=[],
        session_facts=SessionFacts(),
    ))

    assert decision.decision == "clarification"
    assert decision.reason_code == "test"


def test真实Planner使用零温度且仍不挂载业务工具(monkeypatch):
    """稳定性不得依靠非法输出重试，单次 Planner 调用本身应确定。"""
    from agno.models.deepseek import DeepSeek

    from agent.core import planner as planner_module

    model = DeepSeek(id="deepseek-chat", api_key="test-key")
    monkeypatch.setattr(planner_module.ModelConfig, "get_main_model", lambda: model)

    agent = planner_module.create_planner_agent()

    assert agent.model.temperature == 0


async def _bare_log_parse_runner(_planner_input: str):
    """模拟模型漏掉显式字段参数：返回不带 feature_field 的裸 log_parse。"""
    return PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-log-bare",
            "steps": [{"step_id": "log-1", "type": "log_parse"}],
        }
    )


def test显式日志类型短语但计划缺字段时确定性澄清():
    """用户说“把 category 作为日志类型”而计划缺 feature_field 时必须追问，不得静默自动探测。"""
    from agent.core.planner import PlannerService

    planner = PlannerService(runner=_bare_log_parse_runner)
    decision = asyncio.run(planner.plan(
        user_text="把 category 字段作为日志类型",
        conversation_history=[],
        session_facts=SessionFacts(has_logs=True),
    ))

    assert decision.decision == "clarification"
    assert decision.reason_code == "explicit_feature_field_ignored"
    assert not decision.steps


def test复合句缺日志类型提取步骤时确定性澄清():
    """复合句被模型砍掉后半步骤时同样拦截，宁可追问不静默丢意图。"""
    from agent.core.planner import PlannerService

    async def enum_only_runner(_planner_input: str):
        return PlanDecision.model_validate(
            {
                "decision": "execute",
                "plan_id": "plan-enum-only",
                "steps": [
                    {
                        "step_id": "enum-1",
                        "type": "enum_extract",
                        "target_field": "category",
                        "source_ref": "session.logs",
                    }
                ],
            }
        )

    planner = PlannerService(runner=enum_only_runner)
    decision = asyncio.run(planner.plan(
        user_text="提取 category 的枚举值，然后按 category 做日志类型分类",
        conversation_history=[],
        session_facts=SessionFacts(has_logs=True, available_fields=("category",)),
    ))

    assert decision.decision == "clarification"
    assert decision.reason_code == "explicit_feature_field_ignored"


def test无显式短语时守卫不干预裸log_parse():
    """用户没点名字段时裸 log_parse 合法，守卫不得改写。"""
    from agent.core.planner import PlannerService

    planner = PlannerService(runner=_bare_log_parse_runner)
    decision = asyncio.run(planner.plan(
        user_text="日志类型提取",
        conversation_history=[],
        session_facts=SessionFacts(has_logs=True),
    ))

    assert decision.decision == "execute"
    assert decision.steps[0].type == "log_parse"


def test计划已携带feature_field时守卫不干预():
    """计划已带 feature_field 时不构成矛盾，原决策保留。"""
    from agent.core.planner import PlannerService

    async def explicit_runner(_planner_input: str):
        return PlanDecision.model_validate(
            {
                "decision": "execute",
                "plan_id": "plan-log-field",
                "steps": [{"step_id": "log-1", "type": "log_parse", "feature_field": "category"}],
            }
        )

    planner = PlannerService(runner=explicit_runner)
    decision = asyncio.run(planner.plan(
        user_text="把 category 字段作为日志类型",
        conversation_history=[],
        session_facts=SessionFacts(has_logs=True),
    ))

    assert decision.decision == "execute"
    assert decision.steps[0].feature_field == "category"
