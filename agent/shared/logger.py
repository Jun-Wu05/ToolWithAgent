"""
日志配置

支持：
- 控制台输出（实时）
- 文件存储（单一日志文件）
- 所有模块共享同一个日志文件
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


# ============= 单例模式 =============

# 全局日志实例缓存
_loggers = {}

# 全局共享的日志文件
_shared_log_file = None
_shared_error_file = None


def setup_logger(name: str = "agent", level: int = logging.DEBUG) -> logging.Logger:
    """
    设置日志记录器（单例模式）
    
    Args:
        name: 日志记录器名称（用于标识来源，不影响文件名）
        level: 日志级别
    
    Returns:
        配置好的Logger对象
    """
    global _shared_log_file, _shared_error_file
    
    logger = logging.getLogger(name)
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 日志格式器
    # 控制台：紧凑格式
    console_formatter = logging.Formatter(
        '%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. 控制台处理器（实时输出）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 2. 文件处理器（保存日志）- 所有模块共享同一个文件
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # 只在第一次时创建日志文件；每进程至多进入一次该分支
    first_shared_file = _shared_log_file is None
    if first_shared_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _shared_log_file = log_dir / f"app_{timestamp}.log"
        _shared_error_file = log_dir / f"app_errors_{timestamp}.log"

    # 主管日志文件（带 trace 注入的结构化 JSON）
    json_formatter = _StructuredTraceFormatter()
    file_handler = logging.FileHandler(_shared_log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(json_formatter)
    logger.addHandler(file_handler)

    # 错误日志文件（纯文本格式）
    error_formatter = logging.Formatter(
        '%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    error_handler = logging.FileHandler(_shared_error_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(error_formatter)
    logger.addHandler(error_handler)

    if first_shared_file:
        # 首个日志文件建立后立即清理旧日志（#176）：任何产生日志的进程
        # （pytest/子进程/CLI/应用/热重载）创建日志文件时都会经过此分支，
        # 不再依赖应用启动入口。FileHandler 已建立即文件在磁盘上、被 glob
        # 计入总数；清理失败只告警，不影响日志初始化。
        initialize_log_retention()

    # 如果是第一个创建的 logger，输出初始化信息
    if len(_loggers) == 0:
        logger.info(f"日志文件: {_shared_log_file}")
    
    return logger


def cleanup_old_logs(log_dir: Path, prefix: str = "app", keep_count: int = 3):
    """
    清理旧日志文件

    主日志（app_时间戳.log）与错误日志（app_errors_时间戳.log）分别匹配：
    prefix="app" 只匹配 ``app_<数字>.log``，不匹配 ``app_errors_*.log``。

    总数语义（#176）：每前缀保留 **总数 = keep_count** 个文件，活动文件计入
    保留额度且永不进入删除集合——稳态为「当前 + 上一次」而非 keep_count+1。
    文件被占用或删除失败时只记录告警，不抛出异常（WinError 32 降级）。

    Args:
        log_dir: 日志目录
        prefix: 日志文件前缀（"app" 主日志 / "app_errors" 错误日志）
        keep_count: 每前缀保留的文件总数（含活动文件）
    """
    if not log_dir.exists():
        return

    # 精确匹配：prefix 后必须紧跟数字时间戳（避免 app_ 匹配到 app_errors_）
    pattern = f"{prefix}_[0-9]*.log"
    log_files = sorted(log_dir.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)

    # 排除当前正在写入的活动文件（绝不删除打开中的文件），但其数量占用保留额度
    active_files = {_shared_log_file, _shared_error_file}
    active_count = sum(1 for f in log_files if f in active_files)
    candidates = [f for f in log_files if f not in active_files]

    # 删除多余的文件（删除失败只告警，不中断业务）
    for old_file in candidates[max(0, keep_count - active_count):]:
        try:
            old_file.unlink(missing_ok=True)
        except (PermissionError, OSError) as e:
            # WinError 32（文件被占用）等：只记录告警，不抛出
            logging.getLogger("agent").warning(
                f"日志清理跳过被占用文件: {old_file.name} ({e})"
            )


def get_logger(name: str = "agent") -> logging.Logger:
    """获取已配置的日志记录器（单例模式）

    每进程首次创建共享日志文件时自动执行一次保留清理（#176）；
    同进程后续 get_logger 不重复清理。应用入口仍可显式调用
    ``initialize_log_retention()``（幂等）。
    """
    if name in _loggers:
        return _loggers[name]

    logger = setup_logger(name)
    _loggers[name] = logger

    return logger


def initialize_log_retention(log_dir: Optional[Path] = None, keep_count: int = 2) -> None:
    """应用启动时清理旧日志（主日志与错误日志分别保留）。

    幂等：重复调用安全。应在应用入口（chainlit_app.py）启动时调用一次。
    默认 keep_count=2：保留当前运行 + 上一次运行（用于对比调试）。

    Args:
        log_dir: 日志目录，默认为 agent/logs/
        keep_count: 每类日志保留的文件数（默认 2：当前 + 上一次）
    """
    if log_dir is None:
        log_dir = Path(__file__).parent.parent / "logs"
    cleanup_old_logs(log_dir, prefix="app", keep_count=keep_count)
    cleanup_old_logs(log_dir, prefix="app_errors", keep_count=keep_count)


class _StructuredTraceFormatter(logging.Formatter):
    """
    结构化 JSON 日志格式器

    自动注入当前 TraceContext 的 trace_id / span_id 等字段到 JSON 日志中。
    控制台输出使用纯文本格式（不影响可读性），文件输出为 JSON 行格式。
    """

    def __init__(self) -> None:
        super().__init__(datefmt='%Y-%m-%dT%H:%M:%S')

    def format(self, record: logging.LogRecord) -> str:
        """将日志记录格式化为 JSON 行"""
        import time as _time_mod

        # 尝试获取当前链路追踪上下文
        trace_id: Optional[str] = None
        span_id: Optional[str] = None
        try:
            from agent.core.tracing import TraceContext
            ctx = TraceContext.get()
            if ctx is not None:
                trace_id = ctx.trace_id
                span_id = ctx.span_id
        except Exception:
            pass

        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id,
            "span_id": span_id,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 包含异常信息
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
            log_entry["exception_type"] = type(record.exc_info[1]).__name__

        return json.dumps(log_entry, ensure_ascii=False, default=str)
