"""把类型化执行进度渲染为 Chainlit TaskList。"""

from __future__ import annotations

import asyncio
import time

import chainlit as cl

from contracts.progress import ProgressEvent, ProgressPhase, ProgressSink, ProgressStatus


_MESSAGE_TEXT = {
    "planner_understanding": "正在理解指令",
    "planner_completed": "指令理解完成",
    "planner_timeout": "指令理解超时",
    "invalid_plan": "指令计划不合法",
    "planner_unavailable": "指令理解服务不可用",
    "plan_execution_started": "正在执行计划",
    "field_candidates_retrieving": "正在检索字段候选",
    "field_candidates_ready": "字段候选检索完成",
    "field_candidates_failed": "字段候选检索失败",
    "field_mapping_batch_retry": "字段映射批次准备重试",
    "field_mapping_batch_running": "正在执行字段映射",
    "field_mapping_batch_completed": "字段映射批次完成",
    "field_mapping_validating": "正在校验映射结果",
    "field_mapping_writing": "正在写回映射结果",
    "plan_success": "计划执行完成",
    "plan_needs_input": "计划等待补充输入",
    "plan_failed": "计划执行失败",
}

_OPERATION_TEXT = {
    "log_parse": "日志类型提取",
    "field_mapping": "字段映射",
    "enum_extract": "枚举提取",
    "threat_mapping": "威胁映射",
    "fill": "配置填充",
    "remove_mapping": "取消映射",
    "export": "导出",
    "add_fields": "添加字段",
    "delete_fields": "删除字段",
}

_OPERATION_STATE_SUFFIX = {
    "started": "",
    "completed": "完成",
    "needs_input": "等待补充输入",
    "failed": "失败",
}

_SESSION_PROGRESS_SINK_KEY = "chainlit_progress_sink"


def get_session_progress_sink() -> "ChainlitProgressSink":
    """从 Chainlit 用户会话获取唯一进度账本，首次使用时延迟创建。"""
    progress_sink = cl.user_session.get(_SESSION_PROGRESS_SINK_KEY)
    if progress_sink is None:
        progress_sink = ChainlitProgressSink()
        cl.user_session.set(_SESSION_PROGRESS_SINK_KEY, progress_sink)
    return progress_sink


async def reset_session_progress_sink() -> None:
    """如果当前 Chainlit 会话已创建进度账本，则将其重置。"""
    progress_sink = cl.user_session.get(_SESSION_PROGRESS_SINK_KEY)
    if progress_sink is not None:
        await progress_sink.reset()


class _RequestProgressSink(ProgressSink):
    """把一次用户请求的进度事件写入会话级账本。"""

    def __init__(self, ledger: "ChainlitProgressSink", request_id: int) -> None:
        """保存所属会话账本和唯一请求序号。"""
        self._ledger = ledger
        self.request_id = request_id

    async def publish(self, event: ProgressEvent) -> None:
        """保留请求边界后委托会话账本渲染事件。"""
        await self._ledger._publish(self.request_id, event)


class ChainlitProgressSink(ProgressSink):
    """用单个 TaskList 跨请求保留当前会话的安全进度账本。"""

    def __init__(self, heartbeat_seconds: float = 10.0) -> None:
        """初始化任务列表；首次事件到达时才创建 Chainlit 对象。"""
        self._heartbeat_seconds = heartbeat_seconds
        self._task_list = None
        self._tasks_by_step = {}
        self._lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None
        self._last_event_at = time.monotonic()
        self._last_titles = {}
        self._active_task_key: tuple[int, str] | None = None
        self._request_sequence = 0
        self._closed = False

    def begin_request(self) -> _RequestProgressSink:
        """为新请求分配独立作用域，避免重复 step_id 覆盖旧记录。"""
        if self._closed:
            raise RuntimeError("进度账本已关闭")
        self._request_sequence += 1
        return _RequestProgressSink(self, self._request_sequence)

    async def publish(self, event: ProgressEvent) -> None:
        """兼容直接作为 ProgressSink 使用的单请求场景。"""
        await self._publish(0, event)

    async def _publish(self, request_id: int, event: ProgressEvent) -> None:
        """按请求和步骤更新安全进度，不显示模型原始输出。"""
        if self._closed:
            return
        async with self._lock:
            await self._stop_heartbeat()
            self._last_event_at = time.monotonic()
            if self._task_list is None:
                self._task_list = cl.TaskList()

            if event.step_id != "plan":
                title = self._build_title(event)
                task_key = (request_id, event.step_id)
                self._last_titles[task_key] = title
                is_terminal = self._is_terminal_task_event(event)
                task_status = self._task_status(event, is_terminal)
                task = self._tasks_by_step.get(task_key)
                if task is None:
                    task = cl.Task(title=title, status=task_status)
                    self._tasks_by_step[task_key] = task
                    await self._task_list.add_task(task)
                else:
                    task.title = title
                    task.status = task_status
                self._active_task_key = None if is_terminal else task_key
            self._task_list.status = self._list_status(event)
            await self._task_list.send()
            if event.step_id != "plan" and not is_terminal:
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def finish_request(self, request_sink: _RequestProgressSink) -> None:
        """停止已结束请求的心跳，保留会话中已发送的任务。"""
        async with self._lock:
            active_task_key = self._active_task_key
            if active_task_key is None or active_task_key[0] != request_sink.request_id:
                return
            self._active_task_key = None
            await self._stop_heartbeat()

    async def reset(self) -> None:
        """移除当前 TaskList 并清空会话账本，供明确切换数据时使用。"""
        async with self._lock:
            self._active_task_key = None
            await self._stop_heartbeat()
            task_list = self._task_list
            if task_list is not None:
                await task_list.remove()
            self._task_list = None
            self._tasks_by_step.clear()
            self._last_titles.clear()
            self._request_sequence = 0
            self._last_event_at = time.monotonic()

    async def close(self) -> None:
        """停止心跳；已发送的最终任务状态保留在界面中。"""
        self._closed = True
        async with self._lock:
            self._active_task_key = None
            await self._stop_heartbeat()

    def _build_title(self, event: ProgressEvent) -> str:
        """从稳定消息码构建中文标题，不拼接用户输入和模型内容。"""
        title = _MESSAGE_TEXT.get(event.message_code)
        if title is None:
            for operation, operation_text in _OPERATION_TEXT.items():
                prefix = f"{operation}_"
                if event.message_code.startswith(prefix):
                    state = event.message_code.removeprefix(prefix)
                    suffix = _OPERATION_STATE_SUFFIX.get(state)
                    if suffix is not None:
                        title = f"{operation_text}{suffix}"
                    break
        if title is None and event.phase == ProgressPhase.EXECUTION:
            title = "正在执行步骤"
        elif title is None:
            title = "正在处理请求"
        if event.current_batch is not None and event.total_batches is not None:
            title += f"（第 {event.current_batch}/{event.total_batches} 批）"
        if event.elapsed_seconds:
            title += f"，耗时 {event.elapsed_seconds:.1f} 秒"
        return title

    @staticmethod
    def _is_terminal_task_event(event: ProgressEvent) -> bool:
        """只有整步完成、Planner 结束或失败事件才终结任务。"""
        if event.status == ProgressStatus.FAILED:
            return True
        if event.phase == ProgressPhase.COMPLETED:
            return True
        return event.step_id == "planner" and event.status != ProgressStatus.RUNNING

    @staticmethod
    def _task_status(event: ProgressEvent, is_terminal: bool):
        """把领域进度状态映射为 Chainlit TaskStatus。"""
        if event.status == ProgressStatus.FAILED:
            return cl.TaskStatus.FAILED
        if is_terminal and event.status == ProgressStatus.SUCCESS:
            return cl.TaskStatus.DONE
        return cl.TaskStatus.RUNNING

    @staticmethod
    def _list_status(event: ProgressEvent) -> str:
        """生成任务列表顶部的紧凑状态。"""
        if event.step_id in {"plan", "planner"} and event.status == ProgressStatus.SUCCESS:
            return "Done"
        if event.status == ProgressStatus.FAILED:
            return "Failed"
        return "Running..."

    async def _heartbeat_loop(self) -> None:
        """长时间没有新事件时每十秒刷新已等待时间。"""
        try:
            while not self._closed:
                await asyncio.sleep(self._heartbeat_seconds)
                async with self._lock:
                    active_task_key = self._active_task_key
                    if self._closed or active_task_key is None or self._task_list is None:
                        return
                    task = self._tasks_by_step.get(active_task_key)
                    if task is None:
                        return
                    elapsed = time.monotonic() - self._last_event_at
                    task.title = f"{self._last_titles[active_task_key]}，已等待 {elapsed:.0f} 秒"
                    task.status = cl.TaskStatus.RUNNING
                    self._task_list.status = "Running..."
                    await self._task_list.send()
        except asyncio.CancelledError:
            return

    async def _stop_heartbeat(self) -> None:
        """取消旧心跳，避免阶段切换后继续更新过期标题。"""
        heartbeat_task = self._heartbeat_task
        self._heartbeat_task = None
        if heartbeat_task is None or heartbeat_task is asyncio.current_task():
            return
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
