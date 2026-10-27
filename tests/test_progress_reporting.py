"""统一进度协议、超时和 Chainlit 安全渲染的回归测试。"""

import asyncio
from types import SimpleNamespace

from agent.core.planner import PlannerService
from web.chainlit_progress import ChainlitProgressSink
from contracts.progress import ProgressEvent, ProgressPhase, ProgressStatus
from contracts.session_facts import SessionFacts

from factories import make_session_state


class _RecordingProgressSink:
    """在内存中保存类型化进度事件。"""

    def __init__(self) -> None:
        """初始化空事件列表。"""
        self.events = []

    async def publish(self, event: ProgressEvent) -> None:
        """按发布顺序保存事件。"""
        self.events.append(event)


def test计划开始事件包含真实步骤与依赖供诊断投影():
    from application.execution import ExecutionContext, PlanExecutor
    from contracts.planner_models import PlanDecision

    sink = _RecordingProgressSink()
    plan = PlanDecision.model_validate({
        "decision": "execute", "plan_id": "plan-diagnostic",
        "steps": [
            {"step_id": "extract", "type": "log_parse"},
            {"step_id": "parse-again", "type": "log_parse", "depends_on": ["extract"]},
        ],
    })
    asyncio.run(PlanExecutor({}).execute(plan, ExecutionContext(
        session=make_session_state(raw_log_lines=["event=login"]),
        session_facts=SessionFacts(has_logs=True), progress_sink=sink,
    )))
    outline = sink.events[0].planned_steps
    assert [(step.step_id, step.operation, step.depends_on) for step in outline] == [
        ("extract", "log_parse", ()), ("parse-again", "log_parse", ("extract",)),
    ]


def testChainlit同一用户会话复用同一进度账本(monkeypatch):
    """自然语言和按钮入口通过 Chainlit 会话取到同一账本。"""
    import web.chainlit_progress as progress_module

    values = {}

    class _FakeUserSession:
        def get(self, key, default=None):
            return values.get(key, default)

        def set(self, key, value):
            values[key] = value

    monkeypatch.setattr(progress_module.cl, "user_session", _FakeUserSession())

    first = progress_module.get_session_progress_sink()
    second = progress_module.get_session_progress_sink()

    assert first is second
    assert isinstance(first, ChainlitProgressSink)


def testPlanner超时可追踪且明确拒绝执行():
    """Planner 超时必须产生起止事件，并返回不可执行的安全追问。"""
    async def slow_runner(planner_input):
        """模拟超过调用边界的模型服务。"""
        await asyncio.sleep(1)

    sink = _RecordingProgressSink()
    decision = asyncio.run(
        PlannerService(runner=slow_runner, timeout_seconds=0.01).plan(
            user_text="执行字段映射",
            conversation_history=[],
            session_facts=SessionFacts(available_fields=("field_a",)),
            progress_sink=sink,
            progress_plan_id="request-test",
        )
    )

    assert decision.decision == "clarification"
    assert decision.reason_code == "planner_timeout"
    assert [event.message_code for event in sink.events] == [
        "planner_understanding",
        "planner_timeout",
    ]


def testChainlit进度保留全部业务步骤并按首次出现顺序展示(monkeypatch):
    """后续步骤必须追加，不能覆盖已完成的前序业务步骤。"""
    import web.chainlit_progress as progress_module

    task_lists = []

    class _FakeTask:
        def __init__(self, title, status):
            self.title = title
            self.status = status

    class _FakeTaskList:
        def __init__(self):
            self.tasks = []
            self.status = None
            self.snapshots = []
            task_lists.append(self)

        async def add_task(self, task):
            self.tasks.append(task)

        async def send(self):
            self.snapshots.append([(task.title, task.status) for task in self.tasks])

    monkeypatch.setattr(progress_module.cl, "Task", _FakeTask)
    monkeypatch.setattr(progress_module.cl, "TaskList", _FakeTaskList)
    monkeypatch.setattr(
        progress_module.cl,
        "TaskStatus",
        SimpleNamespace(RUNNING="running", DONE="done", FAILED="failed"),
    )

    async def run_case():
        sink = ChainlitProgressSink(heartbeat_seconds=60)
        for step_id, status, message_code in (
            ("plan", ProgressStatus.RUNNING, "plan_execution_started"),
            ("extract", ProgressStatus.RUNNING, "enum_extract_started"),
            ("extract", ProgressStatus.SUCCESS, "enum_extract_completed"),
            ("threat", ProgressStatus.RUNNING, "threat_mapping_started"),
            ("threat", ProgressStatus.SUCCESS, "threat_mapping_completed"),
            ("plan", ProgressStatus.SUCCESS, "plan_success"),
        ):
            await sink.publish(
                ProgressEvent(
                    plan_id="multi-step",
                    step_id=step_id,
                    phase=(
                        ProgressPhase.COMPLETED
                        if status == ProgressStatus.SUCCESS
                        else ProgressPhase.EXECUTION
                    ),
                    status=status,
                    message_code=message_code,
                )
            )
        await sink.close()

    asyncio.run(run_case())

    assert len(task_lists) == 1
    assert task_lists[0].snapshots[-1] == [
        ("枚举提取完成", "done"),
        ("威胁映射完成", "done"),
    ]
    assert task_lists[0].status == "Done"


def testChainlit会话账本跨自然语言与按钮保留业务步骤(monkeypatch):
    """日志提取请求结束后点击字段映射，必须复用同一 TaskList。"""
    import web.chainlit_progress as progress_module

    task_lists = []

    class _FakeTask:
        def __init__(self, title, status):
            self.title = title
            self.status = status

    class _FakeTaskList:
        def __init__(self):
            self.tasks = []
            self.status = None
            task_lists.append(self)

        async def add_task(self, task):
            self.tasks.append(task)

        async def send(self):
            return None

    monkeypatch.setattr(progress_module.cl, "Task", _FakeTask)
    monkeypatch.setattr(progress_module.cl, "TaskList", _FakeTaskList)
    monkeypatch.setattr(
        progress_module.cl,
        "TaskStatus",
        SimpleNamespace(RUNNING="running", DONE="done", FAILED="failed"),
    )

    async def publish(request_sink, step_id, phase, status, message_code):
        await request_sink.publish(
            ProgressEvent(
                plan_id="visible-plan",
                step_id=step_id,
                phase=phase,
                status=status,
                message_code=message_code,
            )
        )

    async def run_case():
        ledger = ChainlitProgressSink(heartbeat_seconds=60)

        natural_language_request = ledger.begin_request()
        await publish(
            natural_language_request,
            "planner",
            ProgressPhase.PLANNING,
            ProgressStatus.SUCCESS,
            "planner_completed",
        )
        await publish(
            natural_language_request,
            "parse",
            ProgressPhase.COMPLETED,
            ProgressStatus.SUCCESS,
            "log_parse_completed",
        )
        await ledger.finish_request(natural_language_request)

        button_request = ledger.begin_request()
        await publish(
            button_request,
            "field-mapping",
            ProgressPhase.COMPLETED,
            ProgressStatus.SUCCESS,
            "field_mapping_completed",
        )
        await ledger.finish_request(button_request)

        repeated_button_request = ledger.begin_request()
        await publish(
            repeated_button_request,
            "field-mapping",
            ProgressPhase.COMPLETED,
            ProgressStatus.SUCCESS,
            "field_mapping_completed",
        )
        await ledger.finish_request(repeated_button_request)

    asyncio.run(run_case())

    assert len(task_lists) == 1
    assert [task.title for task in task_lists[0].tasks] == [
        "指令理解完成",
        "日志类型提取完成",
        "字段映射完成",
        "字段映射完成",
    ]


def testChainlit会话账本保留失败步骤并允许后续请求追加(monkeypatch):
    """一次请求失败不应关闭整个会话账本。"""
    import web.chainlit_progress as progress_module

    task_lists = []

    class _FakeTask:
        def __init__(self, title, status):
            self.title = title
            self.status = status

    class _FakeTaskList:
        def __init__(self):
            self.tasks = []
            self.status = None
            task_lists.append(self)

        async def add_task(self, task):
            self.tasks.append(task)

        async def send(self):
            return None

    monkeypatch.setattr(progress_module.cl, "Task", _FakeTask)
    monkeypatch.setattr(progress_module.cl, "TaskList", _FakeTaskList)
    monkeypatch.setattr(
        progress_module.cl,
        "TaskStatus",
        SimpleNamespace(RUNNING="running", DONE="done", FAILED="failed"),
    )

    async def run_case():
        ledger = ChainlitProgressSink(heartbeat_seconds=60)
        failed_request = ledger.begin_request()
        await failed_request.publish(
            ProgressEvent(
                plan_id="failed-plan",
                step_id="mapping",
                phase=ProgressPhase.COMPLETED,
                status=ProgressStatus.FAILED,
                message_code="field_mapping_failed",
            )
        )
        await ledger.finish_request(failed_request)

        next_request = ledger.begin_request()
        await next_request.publish(
            ProgressEvent(
                plan_id="next-plan",
                step_id="export",
                phase=ProgressPhase.COMPLETED,
                status=ProgressStatus.SUCCESS,
                message_code="export_completed",
            )
        )
        await ledger.finish_request(next_request)

    asyncio.run(run_case())

    assert [(task.title, task.status) for task in task_lists[0].tasks] == [
        ("字段映射失败", "failed"),
        ("导出完成", "done"),
    ]


def testChainlit会话账本重置后移除旧列表并从空列表重新开始(monkeypatch):
    """明确清空数据应同时结束旧任务账本的界面生命周期。"""
    import web.chainlit_progress as progress_module

    task_lists = []

    class _FakeTask:
        def __init__(self, title, status):
            self.title = title
            self.status = status

    class _FakeTaskList:
        def __init__(self):
            self.tasks = []
            self.status = None
            self.removed = False
            task_lists.append(self)

        async def add_task(self, task):
            self.tasks.append(task)

        async def send(self):
            return None

        async def remove(self):
            self.removed = True

    monkeypatch.setattr(progress_module.cl, "Task", _FakeTask)
    monkeypatch.setattr(progress_module.cl, "TaskList", _FakeTaskList)
    monkeypatch.setattr(
        progress_module.cl,
        "TaskStatus",
        SimpleNamespace(RUNNING="running", DONE="done", FAILED="failed"),
    )

    async def run_case():
        ledger = ChainlitProgressSink(heartbeat_seconds=60)
        old_request = ledger.begin_request()
        await old_request.publish(
            ProgressEvent(
                plan_id="old-plan",
                step_id="parse",
                phase=ProgressPhase.COMPLETED,
                status=ProgressStatus.SUCCESS,
                message_code="log_parse_completed",
            )
        )
        await ledger.finish_request(old_request)
        await ledger.reset()

        new_request = ledger.begin_request()
        await new_request.publish(
            ProgressEvent(
                plan_id="new-plan",
                step_id="mapping",
                phase=ProgressPhase.COMPLETED,
                status=ProgressStatus.SUCCESS,
                message_code="field_mapping_completed",
            )
        )
        await ledger.finish_request(new_request)

    asyncio.run(run_case())

    assert len(task_lists) == 2
    assert task_lists[0].removed is True
    assert [task.title for task in task_lists[1].tasks] == ["字段映射完成"]


def testChainlitPlanner与同一步骤的内部阶段原位更新(monkeypatch):
    """Planner 与内部阶段事件均按当前请求的 step_id 去重。"""
    import web.chainlit_progress as progress_module

    task_lists = []

    class _FakeTask:
        def __init__(self, title, status):
            self.title = title
            self.status = status

    class _FakeTaskList:
        def __init__(self):
            self.tasks = []
            self.status = None
            task_lists.append(self)

        async def add_task(self, task):
            self.tasks.append(task)

        async def send(self):
            return None

    monkeypatch.setattr(progress_module.cl, "Task", _FakeTask)
    monkeypatch.setattr(progress_module.cl, "TaskList", _FakeTaskList)
    monkeypatch.setattr(
        progress_module.cl,
        "TaskStatus",
        SimpleNamespace(RUNNING="running", DONE="done", FAILED="failed"),
    )

    async def run_case():
        sink = ChainlitProgressSink(heartbeat_seconds=60)
        events = (
            ("planner", ProgressPhase.PLANNING, ProgressStatus.RUNNING, "planner_understanding"),
            ("planner", ProgressPhase.PLANNING, ProgressStatus.SUCCESS, "planner_completed"),
            ("plan", ProgressPhase.EXECUTION, ProgressStatus.RUNNING, "plan_execution_started"),
            ("mapping", ProgressPhase.EXECUTION, ProgressStatus.RUNNING, "field_mapping_started"),
            ("mapping", ProgressPhase.RETRIEVAL, ProgressStatus.RUNNING, "field_candidates_retrieving"),
            ("mapping", ProgressPhase.COMPLETED, ProgressStatus.SUCCESS, "field_mapping_completed"),
            ("export", ProgressPhase.EXECUTION, ProgressStatus.RUNNING, "export_started"),
            ("export", ProgressPhase.COMPLETED, ProgressStatus.SUCCESS, "export_completed"),
        )
        for step_id, phase, status, message_code in events:
            await sink.publish(
                ProgressEvent(
                    plan_id="deduplicated",
                    step_id=step_id,
                    phase=phase,
                    status=status,
                    message_code=message_code,
                )
            )
        await sink.close()

    asyncio.run(run_case())

    assert len(task_lists) == 1
    assert [(task.title, task.status) for task in task_lists[0].tasks] == [
        ("指令理解完成", "done"),
        ("字段映射完成", "done"),
        ("导出完成", "done"),
    ]


def testPlanExecutor为每个成功业务步骤发布终态事件():
    """每个 StepResult 成功后都必须结束对应 Task，而不是只结束总计划。"""
    from application.execution import ExecutionContext, PlanExecutor
    from contracts.planner_models import PlanDecision, StepResult, StepStatus

    class _SuccessfulExportAdapter:
        async def execute(self, step, context, dependencies):
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus.SUCCESS,
                message="配置已导出",
            )

    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "terminal-events",
            "steps": [
                {
                    "step_id": "first",
                    "type": "export",
                    "source_ref": "session.decoded_config",
                },
                {
                    "step_id": "second",
                    "type": "export",
                    "source_ref": "session.decoded_config",
                },
            ],
        }
    )
    sink = _RecordingProgressSink()

    report = asyncio.run(
        PlanExecutor({"export": _SuccessfulExportAdapter()}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(),
                session_facts=SessionFacts(
                    available_config_refs=("session.decoded_config",),
                ),
                progress_sink=sink,
            ),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert [(event.step_id, event.status, event.message_code) for event in sink.events] == [
        ("plan", ProgressStatus.RUNNING, "plan_execution_started"),
        ("first", ProgressStatus.RUNNING, "export_started"),
        ("first", ProgressStatus.SUCCESS, "export_completed"),
        ("second", ProgressStatus.RUNNING, "export_started"),
        ("second", ProgressStatus.SUCCESS, "export_completed"),
        ("plan", ProgressStatus.SUCCESS, "plan_success"),
    ]


def testPlanExecutor执行前拦截终结当前步骤且不展示后续步骤():
    """待输入结果必须终结当前步骤，并在任何后续 started 事件前停止。"""
    from application.execution import ExecutionContext, PlanExecutor
    from contracts.planner_models import PlanDecision, StepStatus

    plan = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "preflight-stop",
            "steps": [
                {"step_id": "parse", "type": "log_parse"},
                {
                    "step_id": "export",
                    "type": "export",
                    "source_ref": "session.decoded_config",
                },
            ],
        }
    )
    sink = _RecordingProgressSink()

    report = asyncio.run(
        PlanExecutor({}).execute(
            plan,
            ExecutionContext(
                session=make_session_state(),
                session_facts=SessionFacts(),
                progress_sink=sink,
            ),
        )
    )

    assert report.status == StepStatus.NEEDS_INPUT
    assert [(event.step_id, event.status, event.message_code) for event in sink.events] == [
        ("plan", ProgressStatus.RUNNING, "plan_execution_started"),
        ("parse", ProgressStatus.RUNNING, "log_parse_started"),
        ("parse", ProgressStatus.FAILED, "log_parse_needs_input"),
        ("plan", ProgressStatus.FAILED, "plan_needs_input"),
    ]


def testChainlit进度只展示安全阶段且持续发送心跳(monkeypatch):
    """TaskList 应立即发送并持续刷新，且不得拼接用户或模型原始内容。"""
    import web.chainlit_progress as progress_module

    task_lists = []

    class _FakeTask:
        """保存测试所需的任务标题和状态。"""

        def __init__(self, title, status):
            """保存初始化参数。"""
            self.title = title
            self.status = status

    class _FakeTaskList:
        """记录每次 TaskList 发送时的安全标题。"""

        def __init__(self):
            """初始化任务和发送快照。"""
            self.task = None
            self.status = None
            self.sent_titles = []
            task_lists.append(self)

        async def add_task(self, task):
            """保存唯一任务。"""
            self.task = task

        async def send(self):
            """保存本次发送标题。"""
            self.sent_titles.append(self.task.title)

    monkeypatch.setattr(progress_module.cl, "Task", _FakeTask)
    monkeypatch.setattr(progress_module.cl, "TaskList", _FakeTaskList)
    monkeypatch.setattr(
        progress_module.cl,
        "TaskStatus",
        SimpleNamespace(RUNNING="running", DONE="done", FAILED="failed"),
    )

    async def run_case():
        """发布一个运行事件并等待至少一次心跳。"""
        sink = ChainlitProgressSink(heartbeat_seconds=0.01)
        await sink.publish(
            ProgressEvent(
                plan_id="safe-plan",
                step_id="mapping",
                phase=ProgressPhase.MODEL_CALL,
                status=ProgressStatus.RUNNING,
                message_code="field_mapping_batch_running",
                current_batch=1,
                total_batches=12,
            )
        )
        await sink.publish(
            ProgressEvent(
                plan_id="safe-plan",
                step_id="mapping",
                phase=ProgressPhase.RETRIEVAL,
                status=ProgressStatus.SUCCESS,
                message_code="field_candidates_ready",
                current_batch=1,
                total_batches=12,
            )
        )
        await asyncio.sleep(0.025)
        await sink.close()

    asyncio.run(run_case())

    assert len(task_lists) == 1
    assert len(task_lists[0].sent_titles) >= 3
    assert task_lists[0].sent_titles[0] == "正在执行字段映射（第 1/12 批）"
    assert task_lists[0].sent_titles[1] == "字段候选检索完成（第 1/12 批）"
    assert any("已等待" in title for title in task_lists[0].sent_titles[2:])
    assert all("secret-token" not in title for title in task_lists[0].sent_titles)
