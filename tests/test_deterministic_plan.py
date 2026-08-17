"""按钮等确定性入口复用统一 PlanExecutor 的回归测试。"""

import asyncio

from contracts.planner_models import FillStep, StepStatus


def test确定性计划复用统一执行器执行按钮填充步骤(monkeypatch):
    """execute_deterministic_plan 把按钮的类型化 FillStep 经同一 PlanExecutor + 适配器
    执行并渲染，证明按钮入口与自然语言入口共用同一执行核心（回归 #43）。"""
    import web.deterministic_plan as deterministic_plan

    captured = {}

    class _NoOpSink:
        """离线测试不访问 Chainlit TaskList。"""

        async def publish(self, event):
            """忽略进度事件。"""

        async def close(self):
            """忽略关闭。"""

    async def capture_render(report):
        """记录交给渲染器的执行报告。"""
        captured["report"] = report

    monkeypatch.setattr(deterministic_plan, "ChainlitProgressSink", _NoOpSink)
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
    # 真实领域结果：按钮入口同样把枚举映射写回 normalize。
    mappings = session["mapped_sub_rules"][0]["normalize"][0]["mappings"]
    assert mappings == [{"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}]
