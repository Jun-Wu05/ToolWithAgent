"""V2 请求级日志隐私作用域，默认保持 Chainlit 的日志行为。"""
from contextlib import contextmanager
from contextvars import ContextVar
import logging

_private = ContextVar("application_private_logging", default=False)
_make_record = logging.Logger.makeRecord
_standard_keys = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


def _private_record(self, *args, **kwargs):
    """在 extra 已附加后删除请求内容；异步和 to_thread 自动继承作用域。"""
    record = _make_record(self, *args, **kwargs)
    if _private.get():
        for key in tuple(record.__dict__):
            if key not in _standard_keys:
                del record.__dict__[key]
        record.msg = "[V2_APPLICATION] business event"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
    return record


logging.Logger.makeRecord = _private_record


@contextmanager
def private_business_logging():
    """只屏蔽当前请求中的业务日志，不切换全局 logger 级别或处理器。"""
    token = _private.set(True)
    try:
        yield
    finally:
        _private.reset(token)
