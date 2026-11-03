"""V2 请求级日志隐私作用域，默认保持 Chainlit 的日志行为。

作用域内仍屏蔽全部请求内容（消息/参数/异常/extra），但在占位消息后
保留一组安全诊断字段：作用域携带的 run 上下文、白名单 extra（值经
消毒）、异常类型名。``v2.diagnostics`` 是唯一豁免通道——该 logger 的
消息只允许由安全词元（稳定错误码/ID/计数）构造，仅供 V2 Worker 使用。
"""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import sys

_private: ContextVar[dict | None] = ContextVar("application_private_logging", default=None)
_make_record = logging.Logger.makeRecord
_standard_keys = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

# 可保留的 extra 键：全部由本仓代码赋值，值为稳定码/ID/计数，非用户内容。
_SAFE_EXTRA_KEYS = frozenset({
    "run_id", "task_id", "step", "step_id", "operation", "phase",
    "error_category", "error_code", "attempt", "retry_count",
    "batch", "total_batches", "duration_ms",
})
_SAFE_VALUE_LIMIT = 64
_DIAGNOSTIC_LOGGERS = frozenset({"v2.diagnostics"})


def _safe_value(value):
    """标量放行（字符串截断到可打印前缀），其余一律丢弃。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str):
        value = "".join(character for character in value if character.isprintable())
        return value[:_SAFE_VALUE_LIMIT] or None
    return value


def _private_record(self, *args, **kwargs):
    """在 extra 已附加后删除请求内容；异步和 to_thread 自动继承作用域。"""
    record = _make_record(self, *args, **kwargs)
    context = _private.get()
    if context is not None and record.name not in _DIAGNOSTIC_LOGGERS:
        fields = {key: str(value) for key, value in context.items()}
        for key in _SAFE_EXTRA_KEYS:
            value = _safe_value(record.__dict__.get(key))
            if value is not None:
                fields[key] = str(value)
        # logger.exception 在 makeRecord 阶段传的是 exc_info=True，元组要经 sys.exc_info() 解析。
        if record.exc_info:
            active = record.exc_info if isinstance(record.exc_info, tuple) else sys.exc_info()
            if isinstance(active, tuple) and isinstance(active[0], type) \
                    and issubclass(active[0], BaseException):
                fields["exc_type"] = active[0].__name__
        for key in tuple(record.__dict__):
            if key not in _standard_keys:
                del record.__dict__[key]
        record.msg = "[V2_APPLICATION] business event" + "".join(
            f" {key}={fields[key]}" for key in sorted(fields)
        )
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
    return record


logging.Logger.makeRecord = _private_record


@contextmanager
def private_business_logging(**context):
    """只屏蔽当前请求中的业务日志；可选 run/step 上下文随行输出，嵌套合并。"""
    merged = {**(_private.get() or {}), **{key: value for key, value in context.items() if value is not None}}
    token = _private.set(merged)
    try:
        yield
    finally:
        _private.reset(token)
