"""自然语言统一 Planner 入口的离线回归测试。"""

import asyncio
import logging

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
    import application.request_runtime as request_runtime
    import web.user_message_handlers as handlers

    events = []
    rendered = []
    rendered_facts = []
    planner = FakePlanner(decision, events)
    FakeExecutor.events = events
    FakeExecutor.calls = 0

    monkeypatch.setattr(request_runtime, "PlannerService", lambda: planner)
    monkeypatch.setattr(
        request_runtime,
        "create_plan_executor",
        lambda adapters: FakeExecutor(adapters),
    )
    monkeypatch.setattr(request_runtime, "create_default_adapters", lambda team: {})

    lifecycle = []

    class _NoOpRequestSink:
        """在离线入口测试中记录生命周期，不访问 Chainlit 会话。"""

        async def publish(self, event):
            """忽略安全进度事件。"""

    request_sink = _NoOpRequestSink()

    class _FakeLedger:
        def begin_request(self):
            lifecycle.append("begin")
            return request_sink

        async def finish_request(self, finished_sink):
            assert finished_sink is request_sink
            lifecycle.append("finish")

    monkeypatch.setattr(
        handlers,
        "get_session_progress_sink",
        lambda: _FakeLedger(),
    )
    planner.progress_lifecycle = lifecycle

    async def render_decision(decision, **kwargs):
        rendered.append(decision.decision)
        rendered_facts.append(kwargs.get("session_facts"))

    async def render_report(report, **kwargs):
        rendered.append("report")
        rendered_facts.append(kwargs.get("session_facts"))

    async def clear_session(user_session):
        events.append("clear")

    async def reset_progress():
        events.append("progress_reset")

    monkeypatch.setattr(handlers, "render_decision", render_decision)
    monkeypatch.setattr(handlers, "render_execution_report", render_report)
    monkeypatch.setattr(handlers, "_clear_session_data", clear_session)
    monkeypatch.setattr(handlers, "reset_session_progress_sink", reset_progress)

    asyncio.run(handlers.handle_user_message(session or {}, object(), user_text))
    planner.rendered_facts = rendered_facts
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
    assert planner.progress_lifecycle == ["begin", "finish"]


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


def test澄清渲染接收当前安全会话事实(monkeypatch):
    """自然语言入口只把 SessionFacts 投影交给 Composer，不传业务会话。"""
    decision = PlanDecision(
        decision="clarification",
        reason_code="ambiguous_intent",
        question="请选择要执行的操作",
        choices=("枚举提取", "威胁映射"),
    )

    planner, _, _ = _run(
        monkeypatch,
        decision,
        session={"raw_log_lines": ["secret_business_value"]},
    )

    assert planner.rendered_facts[0].has_logs is True
    assert "secret_business_value" not in planner.rendered_facts[0].model_dump_json()


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
    assert events == ["clear", "progress_reset"]
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


def test用户原话与中文结构化意图进入日志且保留诊断字段(monkeypatch, caplog):
    """用户主动提交的原文可审计，Planner 摘要只翻译业务操作而不展开参数值。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-observable",
            "steps": [
                {"step_id": "parse", "type": "log_parse"},
                {
                    "step_id": "enum",
                    "type": "enum_extract",
                    "target_field": "内部字段值不应进入摘要",
                },
            ],
        }
    )
    user_text = "请先提取日志类型，\n再提取事件类型的枚举值"
    caplog.set_level(logging.INFO, logger="user_message_handlers")

    _run(monkeypatch, decision, user_text=user_text)

    log_text = caplog.text
    assert user_text in log_text
    assert "decision_cn=执行计划" in log_text
    assert "operations_cn=['日志类型提取', '枚举提取']" in log_text
    assert "operations=['log_parse', 'enum_extract']" in log_text
    assert "内部字段值不应进入摘要" not in log_text


def test全部业务操作使用稳定中文名称记录(monkeypatch, caplog):
    """中文摘要覆盖 Planner 契约中的全部操作，填充按业务类型区分。"""
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "plan-all-operations",
            "steps": [
                {"step_id": "parse", "type": "log_parse"},
                {
                    "step_id": "mapping",
                    "type": "field_mapping",
                    "source_ref": "session.fields",
                },
                {
                    "step_id": "enum",
                    "type": "enum_extract",
                    "target_field": "敏感参数不展示",
                },
                {
                    "step_id": "threat",
                    "type": "threat_mapping",
                    "source_ref": "step:enum",
                    "depends_on": ["enum"],
                },
                {
                    "step_id": "threat-fill",
                    "type": "fill",
                    "fill_kind": "threat",
                    "target_fields": ["敏感参数不展示"],
                    "source_ref": "step:threat",
                    "config_ref": "session.decoded_config",
                    "depends_on": ["threat"],
                },
                {
                    "step_id": "enum-fill",
                    "type": "fill",
                    "fill_kind": "enum",
                    "target_fields": ["敏感参数不展示"],
                    "source_ref": "session.enum_mapping_table",
                    "config_ref": "session.decoded_config",
                },
                {
                    "step_id": "remove",
                    "type": "remove_mapping",
                    "target_fields": ["敏感参数不展示"],
                    "config_ref": "session.decoded_config",
                },
                {
                    "step_id": "export",
                    "type": "export",
                    "source_ref": "session.decoded_config",
                },
            ],
        }
    )
    caplog.set_level(logging.INFO, logger="user_message_handlers")

    _run(monkeypatch, decision, user_text="执行完整处理流程")

    log_text = caplog.text
    for label in (
        "日志类型提取",
        "字段映射",
        "枚举提取",
        "威胁类型映射",
        "威胁类型填充",
        "枚举填充",
        "取消映射",
        "导出配置",
    ):
        assert label in log_text
    assert "敏感参数不展示" not in log_text


def test非执行决策也记录中文决策摘要(monkeypatch, caplog):
    """澄清和帮助保持可观察，但不伪造不存在的业务步骤。"""
    caplog.set_level(logging.INFO, logger="user_message_handlers")
    clarification = PlanDecision(
        decision="clarification",
        reason_code="needs_context",
        question="请补充信息",
    )
    guidance = PlanDecision(decision="guidance", guidance_code="capabilities")

    _run(monkeypatch, clarification, user_text="请求一")
    _run(monkeypatch, guidance, user_text="请求二")

    assert "decision_cn=需要澄清 operations_cn=[]" in caplog.text
    assert "decision_cn=使用引导 operations_cn=[]" in caplog.text


def test后续威胁链报告先刷新原主报告再渲染链路结果(monkeypatch):
    """跨轮成功链必须更新既有五列表格，不新建第二张主报告。"""
    import web.user_message_handlers as handlers

    report = ExecutionReport(
        plan_id="explicit-alarm-source",
        results=(
            StepResult(
                step_id="threat-chain-fill",
                operation_type="fill",
                status="success",
                changed_count=1,
            ),
        ),
    )
    events = []

    class Ledger:
        def begin_request(self):
            return object()

        async def finish_request(self, _sink):
            events.append("finish")

    async def run_request(**_kwargs):
        return report

    async def refresh_anchor(result, final_config):
        events.append(("refresh", result, final_config))

    async def render_report(result, **_kwargs):
        events.append(("render", result))

    session = {"mapped_sub_rules": [{"name": "threat-rule"}]}
    monkeypatch.setattr(handlers, "get_session_progress_sink", lambda: Ledger())
    monkeypatch.setattr(handlers, "run_user_request", run_request)
    monkeypatch.setattr(
        handlers,
        "refresh_primary_report_anchor",
        refresh_anchor,
        raising=False,
    )
    monkeypatch.setattr(handlers, "render_execution_report", render_report)

    asyncio.run(handlers.handle_user_message(session, object(), "把 alarm_name 映射为威胁类型"))

    assert events == [
        ("refresh", report, session["mapped_sub_rules"]),
        ("render", report),
        "finish",
    ]
