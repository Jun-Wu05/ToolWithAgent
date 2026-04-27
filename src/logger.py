"""
日志配置

支持：
- 控制台输出（实时）
- 文件存储（单一日志文件）
- 所有模块共享同一个日志文件
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


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
    
    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 1. 控制台处理器（实时输出）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 2. 文件处理器（保存日志）- 所有模块共享同一个文件
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # 只在第一次时创建日志文件
    if _shared_log_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _shared_log_file = log_dir / f"app_{timestamp}.log"
        _shared_error_file = log_dir / f"app_errors_{timestamp}.log"
    
    # 主日志文件
    file_handler = logging.FileHandler(_shared_log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 错误日志文件
    error_handler = logging.FileHandler(_shared_error_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # 如果是第一个创建的 logger，输出初始化信息
    if len(_loggers) == 0:
        logger.info(f"日志文件: {_shared_log_file}")
    
    return logger


def cleanup_old_logs(log_dir: Path, prefix: str = "app", keep_count: int = 3):
    """
    清理旧日志文件
    
    Args:
        log_dir: 日志目录
        prefix: 日志文件前缀
        keep_count: 保留最近N个文件
    """
    if not log_dir.exists():
        return
    
    # 查找匹配的日志文件
    pattern = f"{prefix}_*.log"
    log_files = sorted(log_dir.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    
    # 删除多余的文件
    for old_file in log_files[keep_count:]:
        old_file.unlink(missing_ok=True)


def get_logger(name: str = "agent") -> logging.Logger:
    """获取已配置的日志记录器（单例模式）"""
    if name in _loggers:
        return _loggers[name]
    
    logger = setup_logger(name)
    _loggers[name] = logger
    
    # 启动时清理旧日志（保留最近3个）
    log_dir = Path(__file__).parent.parent / "logs"
    cleanup_old_logs(log_dir, "app", keep_count=3)
    
    return logger