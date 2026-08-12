"""Agno 日志桥接与 Token 用量观测。

本模块不提供 Team 路由或专业 Agent 选择；执行适配器按类型化步骤直接选择成员。
"""
import logging as _logging
import os
import re as _re
import sys

from agent.shared.logger import get_logger
from agent.core.model_config import ModelConfig

logger = get_logger("llm_client")

# 模块级标志：Agno 日志拦截是否已安装
_agno_bridge_installed: bool = False

def setup_agno_logging_bridge():
    """
    拦截 Agno 框架内部的 DEBUG/INFO logger，提取 Token 用量信息。

    必须在第一次 Team 调用前执行（通常放在 on_chat_start 的最前面）。
    可重复调用（模块级 _agno_bridge_installed 标志防止重复安装）。
    """
    global _agno_bridge_installed
    if _agno_bridge_installed:
        return None

    _agno_bridge_installed = True

    # 确保项目根目录在sys.path中
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_current_dir)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    from agent.core.model_config import ModelConfig
    model_name = ModelConfig.get_model_id()

    # 预编译正则
    _TOKEN_RE = _re.compile(
        r'Tokens:\s*input=(?P<input>\d+),\s*output=(?P<output>\d+),\s*total=(?P<total>\d+)(?:,\s*cached=(?P<cached>\d+))?'
    )
    _DURATION_RE = _re.compile(r'Duration:\s*(?P<duration>[\d.]+)s')

    class _AgnoTokenHandler(_logging.Handler):
        """捕获 agno.* logger 的 token 信息并写入应用日志"""

        def __init__(self):
            """初始化日志处理器及最近一次成员和耗时状态。"""
            super().__init__(level=_logging.DEBUG)
            self._last_duration_s: float | None = None
            self._last_member_name: str = ""
            self._name_pattern = _re.compile(r'\[(\w+Agent)\]|Member:\s*(\w+)')

        def emit(self, record: _logging.LogRecord):
            """解析 Agno 日志记录，并输出不含敏感原值的用量摘要。"""
            msg = str(record.msg) if record.msg else ""
            args = record.args if record.args else ()

            try:
                if args:
                    msg = msg % args
            except Exception:
                pass

            # 1) 提取 member agent 名称
            name_match = self._name_pattern.search(msg)
            if name_match:
                self._last_member_name = name_match.group(1) or name_match.group(2) or ""

            # 2) 提取 Duration
            dur_match = _DURATION_RE.search(msg)
            if dur_match:
                self._last_duration_s = float(dur_match.group('duration'))

            # 3) 提取 Tokens
            token_match = _TOKEN_RE.search(msg)
            if not token_match:
                return

            input_t = token_match.group('input')
            output_t = token_match.group('output')
            total_t = token_match.group('total')
            cached_t = token_match.group('cached')

            if self._last_member_name:
                label = f"MemberAgent({self._last_member_name})"
            else:
                label = "Team Leader 路由"

            parts = [
                f"模型: {model_name}",
                f"Tokens - 输入: {input_t}, 输出: {output_t}, 总计: {total_t}",
            ]
            if cached_t:
                parts.append(f"缓存: {cached_t}")
            if self._last_duration_s is not None:
                parts.append(f"耗时: {self._last_duration_s:.1f}s")
                self._last_duration_s = None

            logger.info(f"[API] {label}，" + "，".join(parts))

    handler = _AgnoTokenHandler()
    for name in ('agno', 'agno.agent', 'agno.team', 'agno.models', ''):
        logger_obj = _logging.getLogger(name)
        logger_obj.addHandler(handler)
        logger_obj.setLevel(_logging.DEBUG)

    logger.info("[LOGGING_BRIDGE] Agno 日志拦截器已安装，将捕获 Token 用量信息")
    return handler


# ============= 内部函数 =============

def _log_token_usage(result):
    """记录 LLM Token 用量（深度探测 RunResponse 上所有可能存放 token/metrics 的属性）"""
    try:
        from agent.core.model_config import ModelConfig
        model_name = ModelConfig.get_model_id()

        def _emit(label: str, input_tokens, output_tokens, total_tokens, cached_tokens=None, extra_info: str = ""):
            """按统一格式记录一次模型调用的 Token 用量。"""
            parts = [
                f"模型: {model_name}",
                f"Tokens - 输入: {input_tokens}, 输出: {output_tokens}, 总计: {total_tokens}",
            ]
            if cached_tokens is not None:
                parts.append(f"缓存: {cached_tokens}")
            if extra_info:
                parts.append(extra_info)
            logger.info(f"[API] {label}，" + "，".join(parts))

        found_any = False

        # 1）检查 result.usage
        usage = getattr(result, 'usage', None)
        if usage:
            inp = getattr(usage, 'input_tokens', None) or getattr(usage, 'prompt_tokens', None)
            out = getattr(usage, 'output_tokens', None) or getattr(usage, 'completion_tokens', None)
            total = getattr(usage, 'total_tokens', None)
            cached = getattr(usage, 'cached_tokens', None)
            if inp is not None or out is not None:
                _emit("主调用", inp, out, total, cached)
                found_any = True

        # 2）检查 result.metrics
        metrics = getattr(result, 'metrics', None)
        if metrics is not None:
            if isinstance(metrics, dict):
                _inp = metrics.get('input_tokens') or metrics.get('prompt_tokens')
                _out = metrics.get('output_tokens') or metrics.get('completion_tokens')
                _tot = metrics.get('total_tokens')
                _cache = metrics.get('cached_tokens')
                if _inp is not None or _out is not None:
                    _emit("主调用(metrics)", _inp, _out, _tot, _cache)
                    found_any = True
            elif hasattr(metrics, 'input_tokens') or hasattr(metrics, 'total_tokens'):
                _inp = getattr(metrics, 'input_tokens', None)
                _out = getattr(metrics, 'output_tokens', None)
                _tot = getattr(metrics, 'total_tokens', None)
                _dur = getattr(metrics, 'duration', None)
                _extra = f"耗时: {_dur:.1f}s" if _dur is not None else ""
                if _inp is not None or _out is not None:
                    _emit("主调用(metrics)", _inp, _out, _tot, None, _extra)
                    found_any = True

        # 3）检查 result.run_data 与 result.extra
        for attr_name in ('run_data', 'extra', 'run_response'):
            container = getattr(result, attr_name, None)
            if container is None:
                continue
            if isinstance(container, dict):
                for key, val in container.items():
                    _probe_nested(key, val, model_name, _emit)
                    found_any = True
            elif hasattr(container, '__dict__'):
                for key, val in container.__dict__.items():
                    if 'token' in key.lower() or 'usage' in key.lower() or 'metric' in key.lower():
                        logger.info(f"[API] {attr_name}.{key}: {val}")
                        found_any = True

        # 4）检查 result.members 与 result.member_responses
        for attr_name in ('members', 'member_responses'):
            val = getattr(result, attr_name, None)
            if val is None:
                continue
            if isinstance(val, list):
                for idx, item in enumerate(val):
                    _probe_nested(f"Member[{idx}]", item, model_name, _emit)
                    found_any = True
            elif isinstance(val, dict):
                for key, item in val.items():
                    _probe_nested(f"Member[{key}]", item, model_name, _emit)
                    found_any = True

        if not found_any:
            logger.info(f"[API] 模型: {model_name}，Token 用量未获取到（RunResponse 上无 usage/metrics 属性，请依赖 Agno logging bridge）")
    except Exception as e:
        logger.warning(f"[API] Token 用量探测异常: {type(e).__name__}: {e}")


def _probe_nested(label: str, obj, model_name: str, emit_fn):
    """递归探测嵌套对象上的 token 信息"""
    if obj is None:
        return
    if isinstance(obj, dict):
        inp = obj.get('input_tokens') or obj.get('prompt_tokens')
        out = obj.get('output_tokens') or obj.get('completion_tokens')
        total = obj.get('total_tokens')
        cached = obj.get('cached_tokens')
        if inp is not None or out is not None:
            emit_fn(label, inp, out, total, cached)
        for k, v in obj.items():
            if k in ('usage', 'metrics', 'response', 'run_response') and isinstance(v, dict):
                _probe_nested(f"{label}/{k}", v, model_name, emit_fn)
    elif hasattr(obj, '__dict__'):
        usage = getattr(obj, 'usage', None)
        if usage is not None:
            inp = getattr(usage, 'input_tokens', None) or getattr(usage, 'prompt_tokens', None)
            out = getattr(usage, 'output_tokens', None) or getattr(usage, 'completion_tokens', None)
            total = getattr(usage, 'total_tokens', None)
            cached = getattr(usage, 'cached_tokens', None)
            if inp is not None or out is not None:
                emit_fn(label, inp, out, total, cached)
        metrics = getattr(obj, 'metrics', None)
        if metrics is not None and isinstance(metrics, dict):
            _probe_nested(f"{label}/metrics", metrics, model_name, emit_fn)
