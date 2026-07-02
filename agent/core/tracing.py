"""
链路追踪 - trace_id / span_id 生成与上下文管理

基于 contextvars 实现，支持异步环境（Chainlit asyncio）下的请求追踪。
每次用户请求生成唯一 trace_id，每个 LLM 调用生成子 span。

用法:
    from agent.core.tracing import TraceContext, trace_request

    @trace_request("field_mapping")
    async def handle_field_mapping(user_input: str):
        ctx = TraceContext.get()
        logger.info(f"[trace_id={ctx.trace_id}] 开始处理...")

    或手动:
        with TraceContext.new(user_id="user123") as ctx:
            logger.info(f"[trace_id={ctx.trace_id}] ...")
"""

import uuid
import time
import contextvars
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from contextlib import contextmanager
import functools
import asyncio as asyncio_mod


# contextvars 支持异步环境下的请求隔离
_current_trace: contextvars.ContextVar[Optional["TraceContext"]] = contextvars.ContextVar(
    "current_trace", default=None
)


@dataclass
class TraceContext:
    """
    追踪上下文 — 包含 trace_id / span_id / 时间戳等

    Attributes:
        trace_id: 请求级别唯一 ID（贯穿整个用户请求）
        span_id: 当前操作级别唯一 ID（每个 LLM 调用一个 span）
        parent_span_id: 父 span ID
        user_id: 发起请求的用户标识（可选）
        start_time: 当前 span 开始时间
        operation: 当前操作名称
    """

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    parent_span_id: Optional[str] = None
    user_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    operation: str = "root"

    @staticmethod
    def get() -> Optional["TraceContext"]:
        """获取当前请求的追踪上下文"""
        return _current_trace.get()

    @staticmethod
    def set(ctx: "TraceContext") -> None:
        """设置当前请求的追踪上下文"""
        _current_trace.set(ctx)

    @staticmethod
    def reset() -> None:
        """重置追踪上下文"""
        _current_trace.set(None)

    @classmethod
    @contextmanager
    def new(
        cls,
        user_id: Optional[str] = None,
        operation: str = "root",
    ):
        """
        创建新的追踪上下文（上下文管理器）

        Usage:
            with TraceContext.new(user_id="alice") as ctx:
                # ctx 自动设置为当前上下文
                process()
        """
        ctx = cls(
            user_id=user_id,
            operation=operation,
            start_time=time.time(),
        )
        token = _current_trace.set(ctx)
        try:
            yield ctx
        finally:
            _current_trace.reset(token)

    @contextmanager
    def span(self, operation: str):
        """
        在当前 trace 下创建子 span（上下文管理器）

        Usage:
            ctx = TraceContext.get()
            with ctx.span("llm_call"):
                result = await team.run(prompt)
        """
        parent_span_id = self.span_id
        span_ctx = TraceContext(
            trace_id=self.trace_id,
            span_id=uuid.uuid4().hex[:8],
            parent_span_id=parent_span_id,
            user_id=self.user_id,
            start_time=time.time(),
            operation=operation,
        )
        token = _current_trace.set(span_ctx)
        try:
            yield span_ctx
        finally:
            _current_trace.reset(token)

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON 日志）"""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "user_id": self.user_id,
            "operation": self.operation,
            "start_time": self.start_time,
        }

    def to_log_prefix(self) -> str:
        """生成日志前缀字符串"""
        parts = [f"[trace={self.trace_id}][span={self.span_id}]"]
        if self.operation:
            parts.append(f"[op={self.operation}]")
        return "".join(parts)


def trace_request(operation: str = "root"):
    """
    装饰器：为异步函数自动创建追踪上下文

    Usage:
        @trace_request("field_mapping")
        @cl.on_message
        async def on_message(message: cl.Message):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            with TraceContext.new(operation=operation) as ctx:
                from agent.shared.logger import get_logger
                logger = get_logger("tracing")
                logger.info(f"{ctx.to_log_prefix()} 请求开始")
                try:
                    result = await func(*args, **kwargs)
                    elapsed = time.time() - ctx.start_time
                    logger.info(
                        f"{ctx.to_log_prefix()} 请求完成，耗时 {elapsed:.2f}s"
                    )
                    return result
                except Exception as e:
                    elapsed = time.time() - ctx.start_time
                    logger.error(
                        f"{ctx.to_log_prefix()} 请求失败，耗时 {elapsed:.2f}s: {e}"
                    )
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with TraceContext.new(operation=operation) as ctx:
                from agent.shared.logger import get_logger
                logger = get_logger("tracing")
                logger.info(f"{ctx.to_log_prefix()} 请求开始")
                try:
                    result = func(*args, **kwargs)
                    elapsed = time.time() - ctx.start_time
                    logger.info(
                        f"{ctx.to_log_prefix()} 请求完成，耗时 {elapsed:.2f}s"
                    )
                    return result
                except Exception as e:
                    elapsed = time.time() - ctx.start_time
                    logger.error(
                        f"{ctx.to_log_prefix()} 请求失败，耗时 {elapsed:.2f}s: {e}"
                    )
                    raise

        # 根据函数类型返回对应的包装器
        if asyncio_mod.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator