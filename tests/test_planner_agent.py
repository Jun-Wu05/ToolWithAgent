"""独立 PlannerAgent 的离线行为测试。"""

import asyncio

from web.planner_models import PlanDecision
from web.session_facts import SessionFacts


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


def testplanner超时时明确追问且不做关键词兜底():
    from agent.core.planner import PlannerService

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
