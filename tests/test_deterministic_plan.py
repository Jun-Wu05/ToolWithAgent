"""按钮等确定性入口复用统一 PlanExecutor 的回归测试。"""

import asyncio

from contracts.planner_models import FillStep, StepStatus


def test确定性计划复用统一执行器执行按钮填充步骤(monkeypatch):
    """execute_deterministic_plan 把按钮的类型化 FillStep 经同一 PlanExecutor + 适配器
    执行并渲染，证明按钮入口与自然语言入口共用同一执行核心（回归 #43）。"""
    import web.deterministic_plan as deterministic_plan

    captured = {}

    lifecycle = []

    class _NoOpRequestSink:
        """离线测试不访问 Chainlit TaskList。"""

        async def publish(self, event):
            """忽略进度事件。"""

    request_sink = _NoOpRequestSink()

    class _FakeLedger:
        def begin_request(self):
            lifecycle.append("begin")
            return request_sink

        async def finish_request(self, finished_sink):
            assert finished_sink is request_sink
            lifecycle.append("finish")

    async def capture_render(report):
        """记录交给渲染器的执行报告。"""
        captured["report"] = report
        captured["render_count"] = captured.get("render_count", 0) + 1

    monkeypatch.setattr(
        deterministic_plan,
        "get_session_progress_sink",
        lambda: _FakeLedger(),
    )
    monkeypatch.setattr(deterministic_plan, "render_execution_report", capture_render)

    session = {
        "mapped_sub_rules": [{"name": "rule-1", "normalize": [{"index": "event_type3", "mappings": []}]}],
        "enum_preview": [
            {
                "目标字段": "event_type3",
                "mappingType": "EQUAL",
                "orgValue": "attack",
                "mappingValue": "攻击",
            }
        ],
    }
    step = FillStep(
        step_id="enum-fill",
        type="fill",
        fill_kind="enum",
        target_fields=("event_type3",),
        source_ref="session.enum_mapping_table",
        config_ref="session.mapped_sub_rules",
    )

    asyncio.run(
        deterministic_plan.execute_deterministic_plan(
            session, team=None, plan_id="det", steps=[step]
        )
    )

    report = captured["report"]
    assert report.status == StepStatus.SUCCESS
    assert report.results[0].operation_type == "fill"
    assert report.results[0].changed_count == 1
    assert captured["render_count"] == 1
    assert lifecycle == ["begin", "finish"]
    # 真实领域结果：按钮入口同样把枚举映射写回 normalize。
    mappings = session["mapped_sub_rules"][0]["normalize"][0]["mappings"]
    assert mappings == [{"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}]


def test应用入口在慢速威胁链前发布主报告且保持合并返回(monkeypatch):
    """#213：可选回调先发布主报告，未结束的威胁链仍由同一次调用续跑。"""
    import application.request_runtime as runtime
    from application.progress import NullProgressSink
    from contracts.planner_models import ExecutionReport, PlanDecision, StepResult

    primary = ExecutionReport(
        plan_id="det-primary-first",
        results=(
            StepResult(
                step_id="field-mapping",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                message="字段映射完成",
            ),
        ),
    )
    follow_up = StepResult(
        step_id="threat-chain",
        operation_type="threat_chain",
        status=StepStatus.SUCCESS,
        message="威胁类型链路已自动完成",
    )
    chain_started = asyncio.Event()
    allow_chain_finish = asyncio.Event()
    execution_count = 0
    published = []

    async def fake_execute(**_kwargs):
        nonlocal execution_count
        execution_count += 1
        return primary

    async def fake_chain(*, report, **_kwargs):
        chain_started.set()
        await allow_chain_finish.wait()
        return ExecutionReport(plan_id=report.plan_id, results=report.results + (follow_up,))

    async def capture_primary(report):
        published.append(report)

    monkeypatch.setattr(runtime, "_execute_plan_with_threat_transaction", fake_execute)
    monkeypatch.setattr(runtime, "run_threat_chain_after_mapping", fake_chain)
    plan = PlanDecision(
        decision="execute",
        plan_id=primary.plan_id,
        steps=(
            FillStep(
                step_id="field-mapping",
                type="fill",
                fill_kind="enum",
                target_fields=("event_type",),
                source_ref="session.enum_mapping_table",
                config_ref="session.mapped_sub_rules",
            ),
        ),
    )

    async def scenario():
        task = asyncio.create_task(
            runtime.run_deterministic_plan(
                session={},
                team=None,
                plan=plan,
                progress_sink=NullProgressSink(),
                on_primary_report=capture_primary,
            )
        )
        await asyncio.sleep(0)
        if task.done():
            await task
        await asyncio.wait_for(chain_started.wait(), timeout=1)
        assert execution_count == 1
        assert published == [primary]
        assert not task.done()
        allow_chain_finish.set()
        return await task

    final = asyncio.run(scenario())

    assert final.results == primary.results + (follow_up,)


def test网页入口先渲染主报告并仅追加威胁链结果(monkeypatch):
    """#213：慢速续跑不阻塞主报告，最终渲染不重复字段映射结果。"""
    import application.request_runtime as runtime
    import web.deterministic_plan as deterministic_plan
    from contracts.planner_models import ExecutionReport, FieldMappingStep, StepResult

    primary = ExecutionReport(
        plan_id="det-web-primary-first",
        results=(
            StepResult(
                step_id="field-mapping",
                operation_type="field_mapping",
                status=StepStatus.SUCCESS,
                message="字段映射完成",
            ),
        ),
    )
    follow_up = StepResult(
        step_id="threat-chain",
        operation_type="threat_chain",
        status=StepStatus.SUCCESS,
        message="⚠️ 威胁类型链路未完全成功；字段映射结果不受影响",
    )
    chain_started = asyncio.Event()
    allow_chain_finish = asyncio.Event()
    execution_count = 0
    rendered = []
    lifecycle = []

    class _FakeLedger:
        def begin_request(self):
            lifecycle.append("begin")
            return object()

        async def finish_request(self, _finished_sink):
            lifecycle.append("finish")

    async def fake_execute(**_kwargs):
        nonlocal execution_count
        execution_count += 1
        return primary

    async def fake_chain(*, report, **_kwargs):
        chain_started.set()
        await allow_chain_finish.wait()
        return ExecutionReport(plan_id=report.plan_id, results=report.results + (follow_up,))

    async def capture_render(report):
        rendered.append(report)

    monkeypatch.setattr(runtime, "_execute_plan_with_threat_transaction", fake_execute)
    monkeypatch.setattr(runtime, "run_threat_chain_after_mapping", fake_chain)
    monkeypatch.setattr(deterministic_plan, "get_session_progress_sink", lambda: _FakeLedger())
    monkeypatch.setattr(deterministic_plan, "render_execution_report", capture_render)
    step = FieldMappingStep(
        step_id="field-mapping",
        type="field_mapping",
        source_ref="session.fields",
    )

    async def scenario():
        task = asyncio.create_task(
            deterministic_plan.execute_deterministic_plan(
                {}, team=None, plan_id=primary.plan_id, steps=[step]
            )
        )
        await asyncio.wait_for(chain_started.wait(), timeout=1)
        assert execution_count == 1
        assert rendered == [primary]
        assert not task.done()
        allow_chain_finish.set()
        await task

    asyncio.run(scenario())

    assert [report.results for report in rendered] == [primary.results, (follow_up,)]
    assert lifecycle == ["begin", "finish"]
