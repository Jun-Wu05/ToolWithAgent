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


class ChainlitProgressSink(ProgressSink):
    """用单个 TaskList 持续展示安全阶段进度和等待心跳。"""

    def __init__(self, heartbeat_seconds: float = 10.0) -> None:
        """初始化任务列表；首次事件到达时才创建 Chainlit 对象。"""
        self._heartbeat_seconds = heartbeat_seconds
        self._task_list = None
        self._task = None
        self._lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None
        self._last_event_at = time.monotonic()
        self._last_title = "正在处理请求"
        self._closed = False

    async def publish(self, event: ProgressEvent) -> None:
        """更新当前业务阶段；事件只使用消息码，不显示模型原始输出。"""
        if self._closed:
            return
        async with self._lock:
            await self._stop_heartbeat()
            self._last_event_at = time.monotonic()
            title = self._build_title(event)
            self._last_title = title
            task_status = self._task_status(event.status)
            if self._task_list is None:
                self._task_list = cl.TaskList()
            if self._task is None:
                self._task = cl.Task(title=title, status=task_status)
                await self._task_list.add_task(self._task)
            else:
                self._task.title = title
                self._task.status = task_status
            self._task_list.status = self._list_status(event)
            await self._task_list.send()
            if event.status == ProgressStatus.RUNNING:
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def close(self) -> None:
        """停止心跳；已发送的最终任务状态保留在界面中。"""
        self._closed = True
        async with self._lock:
            await self._stop_heartbeat()

    def _build_title(self, event: ProgressEvent) -> str:
        """从稳定消息码构建中文标题，不拼接用户输入和模型内容。"""
        title = _MESSAGE_TEXT.get(event.message_code)
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
    def _task_status(status: ProgressStatus):
        """把领域进度状态映射为 Chainlit TaskStatus。"""
        if status == ProgressStatus.SUCCESS:
            return cl.TaskStatus.DONE
        if status == ProgressStatus.FAILED:
            return cl.TaskStatus.FAILED
        return cl.TaskStatus.RUNNING

    @staticmethod
    def _list_status(event: ProgressEvent) -> str:
        """生成任务列表顶部的紧凑状态。"""
        if event.status == ProgressStatus.SUCCESS:
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
                    if self._closed or self._task is None or self._task_list is None:
                        return
                    elapsed = time.monotonic() - self._last_event_at
                    self._task.title = f"{self._last_title}，已等待 {elapsed:.0f} 秒"
                    self._task.status = cl.TaskStatus.RUNNING
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