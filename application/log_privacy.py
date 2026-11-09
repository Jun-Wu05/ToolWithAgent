"""V2 Run 日志上下文；Chainlit 沿用共享 logger 的原有格式。"""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import traceback

from contracts.model_call_diagnostics import redact_text

_private: ContextVar[dict | None] = ContextVar("application_private_logging", default=None)
_run_recorder: ContextVar[object | None] = ContextVar("application_run_log_recorder", default=None)
_make_record = logging.Logger.makeRecord

# 可保留的 extra 键：全部由本仓代码赋值，值为稳定码/ID/计数，非用户内容。
_SAFE_EXTRA_KEYS = frozenset({
    "run_id", "task_id", "step", "step_id", "operation", "phase",
    "error_category", "error_code", "attempt", "retry_count",
    "batch", "total_batches", "duration_ms",
})
_SAFE_VALUE_LIMIT = 64
_SECRET_EXTRA_KEYS = frozenset({"authorization", "cookie", "api_key", "apikey", "password", "secret", "token"})


def _safe_value(value):
    """标量放行（字符串截断到可打印前缀），其余一律丢弃。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str):
        value = "".join(character for character in value if character.isprintable())
        return redact_text(value[:_SAFE_VALUE_LIMIT]) or None
    return value


def _private_record(self, *args, **kwargs):
    """在 extra 已附加后删除请求内容；异步和 to_thread 自动继承作用域。"""
    record = _make_record(self, *args, **kwargs)
    context = _private.get()
    if context is not None:
        for key, value in list(record.__dict__.items()):
            if key.lower() in _SECRET_EXTRA_KEYS:
                record.__dict__[key] = "[REDACTED]"
            elif isinstance(value, str):
                record.__dict__[key] = redact_text(value)
        fields = dict(context)
        for key in _SAFE_EXTRA_KEYS:
            value = _safe_value(record.__dict__.get(key))
            if value is not None:
                record.__dict__[key] = value
                fields[key] = value
        record.__dict__.update(context)
        prefix = " ".join(f"{key}={value}" for key, value in fields.items())
        message = (f"[{prefix}] " if prefix else "") + (redact_text(record.getMessage()) or "")
        record.msg = message
        record.args = ()
        if record.exc_info:
            record.exc_text = redact_text("".join(traceback.format_exception(*record.exc_info)))
            if isinstance(record.exc_info, tuple) and record.exc_info[0]:
                record.msg += f" exc_type={record.exc_info[0].__name__}"
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info)
        recorder = _run_recorder.get()
        if recorder is not None:
            try:
                recorder({"created_at": record.created, "level": record.levelname.lower(),
                          "logger": record.name, "message": message,
                          "exception": record.exc_text, **context})
            except Exception:
                pass
    return record


logging.Logger.makeRecord = _private_record


def bind_run_log_recorder(recorder):
    return _run_recorder.set(recorder)


def reset_run_log_recorder(token):
    _run_recorder.reset(token)


def bind_run_context(**context):
    return _private.set({key: value for key, value in context.items() if value is not None})


def reset_run_context(token):
    _private.reset(token)


@contextmanager
def private_business_logging(**context):
    """绑定 Run/步骤；原始消息保留，秘密值在输出前遮盖。"""
    merged = {**(_private.get() or {}), **{key: value for key, value in context.items() if value is not None}}
    token = _private.set(merged)
    try:
        yield
    finally:
        _private.reset(token)
