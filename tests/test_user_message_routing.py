"""自然语言统一 Planner 入口的离线回归测试。"""

import asyncio

from contracts.planner_models import ExecutionReport, PlanDecision, StepResult


class FakePlanner:
    """返回预设决策并记录规划时业务执行器是否已被调用。"""

    def __init__(self, decision, events):
        self.decision = decision
        self.events = events
        self.calls = 0

    async def plan(self, **kwargs):
        """记录一次规划调用和调用顺序。"""
        self.calls += 1
        self.events.append("planner")
        return self.decision


class FakeExecutor:
    """记录执行调用，返回最小成功报告。"""

    events = None
    calls = 0

    def __init__(self, adapters):
        """忽略适配器内容，只验证入口层调用顺序。"""

    async def execute(self, plan, context):
        """在 Planner 决策之后记录执行。"""
        type(self).calls += 1
        type(self).events.append("executor")
        step = plan.steps[0]
        return ExecutionReport(
            plan_id=plan.plan_id,
            results=(StepResult(step_id=step.step_id, operation_type=step.type, status="success"),),
        )


def _run(monkeypatch, decision, user_text="处理请求", session=None):
    """运行入口并返回 Planner、事件顺序和渲染类型。"""
    import web.user_message_handlers as handlers

    events = []
    rendered = []
    planner = FakePlanner(decision, events)
    FakeExecutor.events = events
    FakeExecutor.calls = 0

    monkeypatch.setattr(handlers, "_get_planner_service", lambda: planner)
    monkeypatch.setattr(handlers, "PlanExecutor", FakeExecutor)
    monkeypatch.setattr(handlers, "create_default_adapters", lambda team: {})

    class _NoOpProgressSink:
        """在离线入口测试中记录生命周期，不访问 Chainlit 会话。"""

        async def publish(self, event):
            """忽略安全进度事件。"""

        async def close(self):
            """记录请求结束时的关闭动作。"""

    monkeypatch.setattr(handlers, "_create_progress_sink", _NoOpProgressSink)

    async def render_decision(decision):
        rendered.append(decision.decision)

    async def render_report(report):
        rendered.append("report")

    async def clear_session(user_session):
        events.append("clear")

    monkeypatch.setattr(handlers, "render_decision", render_decision)
    monkeypatch.setattr(handlers, "render_execution_report", render_report)
    monkeypatch.setattr(handlers, "_clear_session_data", clear_session)

    asyncio.run(handlers.handle_user_message(session or {}, object(), user_text))
    return planner, events, rendered


def test每条自然语言恰好调用planner一次且返回前不执行(monkeypatch):
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-one",
            "steps": [{"step_id": "parse", "type": "log_parse"}],
        }
    )

    planner, events, rendered = _run(monkeypatch, decision)

    assert planner.calls == 1
    assert events == ["planner", "executor"]
    assert FakeExecutor.calls == 1
    assert rendered == ["report"]


def test意图冲突返回澄清且不调用执行器(monkeypatch):
    decision = PlanDecision(
        decision="clarification",
        reason_code="ambiguous_intent",
        question="请选择要执行的操作",
        choices=("枚举提取", "威胁映射"),
    )

    planner, events, rendered = _run(
        monkeypatch,
        decision,
        user_text="日志类型字段有哪些枚举值",
    )

    assert planner.calls == 1
    assert events == ["planner"]
    assert FakeExecutor.calls == 0
    assert rendered == ["clarification"]


def test帮助决策不调用执行器(monkeypatch):
    """新手帮助返回 guidance，Planner 调用一次但不进入 PlanExecutor（回归 #42）。"""
    decision = PlanDecision(decision="guidance", guidance_code="capabilities")

    planner, events, rendered = _run(monkeypatch, decision, user_text="你能做什么")

    assert planner.calls == 1
    assert events == ["planner"]
    assert FakeExecutor.calls == 0
    assert rendered == ["guidance"]


def testplanner不可用时不走关键词或router兜底(monkeypatch):
    decision = PlanDecision(
        decision="clarification",
        reason_code="planner_unavailable",
        question="服务暂时不可用，请重试",
    )

    planner, events, rendered = _run(
        monkeypatch,
        decision,
        user_text="提取 src_ip 的枚举值",
        session={"raw_log_lines": ["src_ip=1.1.1.1"]},
    )

    assert planner.calls == 1
    assert events == ["planner"]
    assert FakeExecutor.calls == 0
    assert rendered == ["clarification"]


def test明确清空事件不调用planner(monkeypatch):
    decision = PlanDecision(
        decision="guidance",
        guidance_code="unused",
    )

    planner, events, rendered = _run(monkeypatch, decision, user_text="清空数据")

    assert planner.calls == 0
    assert events == ["clear"]
    assert rendered == []


def test包含清空词的普通句子仍交给planner(monkeypatch):
    decision = PlanDecision(
        decision="clarification",
        reason_code="needs_context",
        question="请说明要清空哪些映射",
    )

    planner, events, _ = _run(monkeypatch, decision, user_text="清空 event_type3 的映射")

    assert planner.calls == 1
    assert events == ["planner"]
