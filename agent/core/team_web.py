"""
Team Web 封装层

提供Web应用使用的Team调用接口
- 线程安全
- 会话隔离
- 超时控制
"""

import threading
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from agent.core.team import get_team_instance, create_data_mapping_team

logger = logging.getLogger("team_web")


class TeamManager:
    """
    Team管理器 - 用于Web应用
    
    特性：
    - 单例模式，避免重复创建
    - 线程安全
    - 状态跟踪
    """
    
    _instance: Optional['TeamManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._team = None
        self._initialized = True
        self._last_request_time: Optional[datetime] = None
        self._request_count = 0
        logger.info("TeamManager 初始化")
    
    @property
    def team(self):
        """获取Team实例（延迟初始化）"""
        if self._team is None:
            logger.info("首次访问Team，创建实例...")
            self._team = get_team_instance()
        return self._team
    
    def run_task(self, prompt: str, timeout: int = 300) -> Dict[str, Any]:
        """
        执行任务（带超时控制）
        
        Args:
            prompt: 用户请求
            timeout: 超时时间（秒）
        
        Returns:
            {"success": bool, "response": str, "error": str}
        """
        self._request_count += 1
        self._last_request_time = datetime.now()
        
        result = {"success": False, "response": None, "error": None}
        
        def run():
            try:
                response = self.team.run(prompt)
                if hasattr(response, 'content'):
                    result["response"] = response.content
                else:
                    result["response"] = str(response)
                result["success"] = True
                logger.info(f"✅ Team响应成功 (请求#{self._request_count})")
            except Exception as e:
                result["error"] = str(e)
                logger.error(f"❌ Team错误: {str(e)}")
        
        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            result["error"] = f"请求超时（{timeout}秒）"
            logger.warning(f"⏰ Team请求超时")
        
        return result
    
    def reset(self):
        """重置Team实例"""
        self._team = None
        self._request_count = 0
        logger.info("TeamManager 已重置")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "initialized": self._initialized,
            "request_count": self._request_count,
            "last_request_time": self._last_request_time.isoformat() if self._last_request_time else None,
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
