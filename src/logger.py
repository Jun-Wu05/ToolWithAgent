"""
日志配置

支持：
- 控制台输出（实时）
- 文件存储（带时间戳）
- 自动清空旧日志
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(name: str = "agent", level: int = logging.DEBUG) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别
    
    Returns:
        配置好的Logger对象
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 1. 控制台处理器（实时输出）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 2. 文件处理器（保存日志）
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # 日志文件名带时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{name}_{timestamp}.log"
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    logger.info(f"日志文件: {log_file}")
    
    # 3. 错误日志单独记录
    error_file = log_dir / f"{name}_errors_{timestamp}.log"
    error_handler = logging.FileHandler(error_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # 启动时清理旧日志（保留最近3个）
    cleanup_old_logs(log_dir, name, keep_count=3)
    
    return logger


def cleanup_old_logs(log_dir: Path, prefix: str, keep_count: int = 3):
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
    """获取已配置的日志记录器"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
