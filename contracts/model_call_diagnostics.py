"""Optional, request-scoped model-call evidence for V2 Run diagnosis.

Only the V2 Worker binds a recorder. Ordinary Application and Chainlit calls
keep their existing behavior, and recording failure never changes a model call.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
from functools import wraps
import re
import time
from typing import Callable
from uuid import uuid4


_recorder: ContextVar[Callable[[dict], None] | None] = ContextVar("model_call_recorder", default=None)
_scope: ContextVar[str | None] = ContextVar("model_call_scope", default=None)
_secret = re.compile(r"(?i)([\"']?\b(?:authorization|cookie|api[_-]?key|password|secret|token)\b[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s,;\"'}]+")
_bearer = re.compile(r"(?i)\bbearer\s+[^\s,;\"']+")
_credential_header = re.compile(r"(?im)^(\s*(?:authorization|cookie|set-cookie)\s*:\s*)[^\r\n]*")
_quoted_secret = re.compile(r"(?i)([\"'](?:authorization|cookie|api[_-]?key|password|secret|token)[\"']\s*:\s*[\"'])[^\"']*([\"'])")


def bind_recorder(recorder: Callable[[dict], None]) -> Token:
    return _recorder.set(recorder)


def reset_recorder(token: Token) -> None:
    _recorder.reset(token)


def set_scope(scope_id: str | None) -> Token:
    return _scope.set(scope_id)


def reset_scope(token: Token) -> None:
    _scope.reset(token)


def redact_text(value: object, api_key: str | None = None) -> str | None:
    """Bound text and remove known credential values and credential assignments."""
    if not isinstance(value, str):
        return None
    value = value[:4096]
    if api_key:
        value = value.replace(api_key, "[REDACTED]")
    value = _credential_header.sub(lambda match: match.group(1) + "[REDACTED]", value)
    value = _quoted_secret.sub(lambda match: match.group(1) + "[REDACTED]" + match.group(2), value)
    value = _secret.sub(lambda match: match.group(1) + "[REDACTED]", value)
    return _bearer.sub("Bearer [REDACTED]", value)


def classify_error(exc: Exception) -> tuple[str, int | None]:
    """Use exception types and HTTP status, never provider prose, for taxonomy."""
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if isinstance(status, int):
        if status in (401, 403):
            return "model_authentication", status
        if status == 429:
            return "model_rate_limited", status
        if status == 404:
            return "model_unavailable", status
        if status >= 500:
            return "provider_unavailable", status
        return "provider_request_failed", status
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & {"ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "APITimeoutError", "TimeoutError"}:
        return "model_timeout", None
    if names & {"ConnectError", "ReadError", "WriteError", "APIConnectionError", "ConnectionError"}:
        return "model_connection", None
    if names & {"JSONDecodeError", "ValidationError", "KeyError", "TypeError"}:
        return "model_response_format", None
    return "model_unclassified", None


def _message_text(messages: object) -> str | None:
    if not isinstance(messages, (list, tuple)):
        return None
    parts = []
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            parts.append(content)
        if sum(map(len, parts)) >= 4096:
            break
    return "\n".join(parts) if parts else None


def record_call(provider, model_id, api_key, started_at, start, request, response=None, exc=None, params=None):
    recorder = _recorder.get()
    if recorder is None:
        return
    try:
        code, status = classify_error(exc) if exc is not None else (None, None)
        event = {"request_id": str(uuid4()), "scope_id": _scope.get(), "provider": provider,
                 "model": model_id, "started_at": started_at,
                 "finished_at": datetime.now(timezone.utc).isoformat(),
                 "duration_ms": max(0, round((time.monotonic() - start) * 1000)),
                 "status": "failed" if exc is not None else "succeeded", "error_code": code,
                 "http_status": status, "request": redact_text(request, api_key),
                 "response": redact_text(response, api_key), "params": params or {},
                 "request_truncated": isinstance(request, str) and len(request) > 4096,
                 "response_truncated": isinstance(response, str) and len(response) > 4096}
        recorder(event)
    except Exception:
        # Diagnostics are observational; a storage outage cannot fail user work.
        pass


def instrument_model(model, provider: str, model_id: str, api_key: str | None = None):
    """Wrap Agno's real invocation seams, preserving the model's public API."""
    if getattr(model, "_model_diagnostics_wrapped", False):
        return model
    params = {key: value for key in ("temperature", "top_p", "max_tokens")
              if isinstance((value := getattr(model, key, None)), (int, float)) and not isinstance(value, bool)}
    for name in ("invoke", "ainvoke", "invoke_stream", "ainvoke_stream"):
        original = getattr(model, name, None)
        if original is None:
            continue
        if name == "ainvoke":
            @wraps(original)
            async def async_call(*args, __original=original, **kwargs):
                if _recorder.get() is None:
                    return await __original(*args, **kwargs)
                start, started_at = time.monotonic(), datetime.now(timezone.utc).isoformat()
                request = _message_text(args[0] if args else None)
                try:
                    result = await __original(*args, **kwargs)
                except Exception as exc:
                    record_call(provider, model_id, api_key, started_at, start, request, exc=exc, params=params)
                    raise
                record_call(provider, model_id, api_key, started_at, start, request,
                      (getattr(args[1], "content", None) if len(args) > 1 else None) or getattr(result, "content", None), params=params)
                return result
            setattr(model, name, async_call)
        elif name == "invoke":
            @wraps(original)
            def sync_call(*args, __original=original, **kwargs):
                if _recorder.get() is None:
                    return __original(*args, **kwargs)
                start, started_at = time.monotonic(), datetime.now(timezone.utc).isoformat()
                request = _message_text(args[0] if args else None)
                try:
                    result = __original(*args, **kwargs)
                except Exception as exc:
                    record_call(provider, model_id, api_key, started_at, start, request, exc=exc, params=params)
                    raise
                record_call(provider, model_id, api_key, started_at, start, request,
                      (getattr(args[1], "content", None) if len(args) > 1 else None) or getattr(result, "content", None), params=params)
                return result
            setattr(model, name, sync_call)
        elif name == "ainvoke_stream":
            @wraps(original)
            async def async_stream(*args, __original=original, **kwargs):
                if _recorder.get() is None:
                    async for chunk in __original(*args, **kwargs):
                        yield chunk
                    return
                start, started_at = time.monotonic(), datetime.now(timezone.utc).isoformat()
                request = _message_text(args[0] if args else None)
                try:
                    async for chunk in __original(*args, **kwargs):
                        yield chunk
                except Exception as exc:
                    record_call(provider, model_id, api_key, started_at, start, request, exc=exc, params=params)
                    raise
                record_call(provider, model_id, api_key, started_at, start, request,
                      getattr(args[1], "content", None) if len(args) > 1 else None, params=params)
            setattr(model, name, async_stream)
        else:
            @wraps(original)
            def sync_stream(*args, __original=original, **kwargs):
                if _recorder.get() is None:
                    yield from __original(*args, **kwargs)
                    return
                start, started_at = time.monotonic(), datetime.now(timezone.utc).isoformat()
                request = _message_text(args[0] if args else None)
                try:
                    yield from __original(*args, **kwargs)
                except Exception as exc:
                    record_call(provider, model_id, api_key, started_at, start, request, exc=exc, params=params)
                    raise
                record_call(provider, model_id, api_key, started_at, start, request,
                      getattr(args[1], "content", None) if len(args) > 1 else None, params=params)
            setattr(model, name, sync_stream)
    model._model_diagnostics_wrapped = True
    return model
