"""统一进度协议、超时和 Chainlit 安全渲染的回归测试。"""

import asyncio
from types import SimpleNamespace

from agent.core.planner import PlannerService
from web.chainlit_progress import ChainlitProgressSink
from web.progress import ProgressEvent, ProgressPhase, ProgressStatus
from web.session_facts import SessionFacts


class _RecordingProgressSink:
    """在内存中保存类型化进度事件。"""

    def __init__(self) -> None:
        """初始化空事件列表。"""
        self.events = []

    async def publish(self, event: ProgressEvent) -> None:
        """按发布顺序保存事件。"""
        self.events.append(event)


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
        await asyncio.sleep(0.025)
        await sink.close()

    asyncio.run(run_case())

    assert len(task_lists) == 1
    assert len(task_lists[0].sent_titles) >= 2
    assert task_lists[0].sent_titles[0] == "正在执行字段映射（第 1/12 批）"
    assert any("已等待" in title for title in task_lists[0].sent_titles[1:])
    assert all("secret-token" not in title for title in task_lists[0].sent_titles)