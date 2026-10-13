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
