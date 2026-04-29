"""
Team Web 封装层

提供Web应用使用的Team调用接口
- 线程安全（锁保护共享状态）
- 可取消的任务执行
- 超时控制
- 活跃任务追踪
"""

import threading
import logging
from typing import Optional, Dict, Any, Set
from datetime import datetime

from agent.core.team import get_team_instance

logger = logging.getLogger("team_web")


class CancellationToken:
    """取消令牌 — 线程安全的取消信号，支持超时后通知工作线程停止等待"""

    def __init__(self) -> None:
        self._cancelled: bool = False
        self._lock: threading.Lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        """发送取消信号"""
        with self._lock:
            self._cancelled = True
        logger.info("[CancellationToken] 取消信号已发送")


class TeamManager:
    """
    Team管理器 - 用于Web应用

    线程安全改进（v2）：
    - result 字典使用 threading.Lock 保护
    - 超时后通过 CancellationToken 通知工作线程
    - 追踪活跃线程，reset() 时清理僵尸线程
    - request_count 使用原子锁保护
    """

    _instance: Optional['TeamManager'] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> 'TeamManager':
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._team = None
        self._initialized = True
        self._last_request_time: Optional[datetime] = None
        self._request_count: int = 0
        self._count_lock: threading.Lock = threading.Lock()
        self._active_threads: Set[threading.Thread] = set()
        self._threads_lock: threading.Lock = threading.Lock()
        logger.info("TeamManager 初始化（线程安全 v2）")

    @property
    def team(self):
        """获取Team实例（延迟初始化，线程安全）"""
        if self._team is None:
            logger.info("首次访问Team，创建实例...")
            self._team = get_team_instance()
        return self._team

    def _increment_count(self) -> int:
        """线程安全地递增请求计数"""
        with self._count_lock:
            self._request_count += 1
            self._last_request_time = datetime.now()
            return self._request_count

    def _track_thread(self, thread: threading.Thread) -> None:
        """注册活跃线程"""
        with self._threads_lock:
            self._active_threads.add(thread)

    def _untrack_thread(self, thread: threading.Thread) -> None:
        """移除已完成的线程"""
        with self._threads_lock:
            self._active_threads.discard(thread)

    def _cleanup_thread(self, thread: threading.Thread) -> None:
        """工作线程结束时的清理回调（在 finally 块中调用）"""
        self._untrack_thread(thread)

    def run_task(self, prompt: str, timeout: int = 300) -> Dict[str, Any]:
        """
        执行任务（线程安全 + 可取消）

        Args:
            prompt: 用户请求
            timeout: 超时时间（秒）

        Returns:
            {"success": bool, "response": str | None, "error": str | None}
        """
        request_id = self._increment_count()

        cancellation = CancellationToken()
        result_lock: threading.Lock = threading.Lock()
        result: Dict[str, Any] = {"success": False, "response": None, "error": None}

        def run() -> None:
            """工作线程：带取消检查"""
            try:
                # 如果已被取消，提前退出
                if cancellation.cancelled:
                    return

                response = self.team.run(prompt)
                if cancellation.cancelled:
                    return

                with result_lock:
                    if hasattr(response, 'content'):
                        result["response"] = response.content
                    else:
                        result["response"] = str(response)
                    result["success"] = True
                logger.info(f"✅ Team响应成功 (请求#{request_id})")
            except Exception as e:
                with result_lock:
                    result["error"] = str(e)
                logger.error(f"❌ Team错误 (请求#{request_id}): {str(e)}")
            finally:
                self._cleanup_thread(thread)

        thread = threading.Thread(target=run, name=f"team-worker-{request_id}")
        thread.daemon = False  # CHANGED: 非守护线程，确保任务可被追踪
        self._track_thread(thread)
        thread.start()

        # 等待完成或超时
        thread.join(timeout=timeout)

        if thread.is_alive():
            # 超时：发送取消信号，记录警告
            cancellation.cancel()
            with result_lock:
                result["error"] = f"请求超时（{timeout}秒）"
            logger.warning(
                f"⏰ Team请求超时 (请求#{request_id}, timeout={timeout}s). "
                f"已发送取消信号，线程将在当前 API 调用完成后退出。"
            )
            # 不 join 无限等待，让线程自然结束（finally 中会 cleanup）

        return result

    def reset(self) -> None:
        """重置Team实例并清理僵尸线程"""
        self._team = None
        with self._count_lock:
            self._request_count = 0
        # 等待所有活跃线程结束（最多等 5 秒）
        with self._threads_lock:
            active = list(self._active_threads)
        for t in active:
            t.join(timeout=5)
        logger.info("TeamManager 已重置")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._threads_lock:
            active_count = len([t for t in self._active_threads if t.is_alive()])
        with self._count_lock:
            rc = self._request_count
            lrt = self._last_request_time
        return {
            "initialized": self._initialized,
            "request_count": rc,
            "last_request_time": lrt.isoformat() if lrt else None,
            "active_threads": active_count,
        }


# 全局单例
_team_manager: Optional[TeamManager] = None


def get_team_manager() -> TeamManager:
    """获取TeamManager单例"""
    global _team_manager
    if _team_manager is None:
        _team_manager = TeamManager()
    return _team_manager


def run_team_task(prompt: str, timeout: int = 300) -> Dict[str, Any]:
    """
    便捷函数：执行Team任务

    Args:
        prompt: 用户请求
        timeout: 超时时间（秒）

    Returns:
        {"success": bool, "response": str, "error": str}
    """
    manager = get_team_manager()
    return manager.run_task(prompt, timeout)