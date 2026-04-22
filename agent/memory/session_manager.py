"""
会话管理器

基于Agno原生SqliteDb的会话管理
提供会话持久化、状态共享、历史记录功能
"""

import os
from typing import Optional, Dict, Any

from agno.db.sqlite import SqliteDb
from agno.agent import Agent


class SessionManager:
    """
    会话管理器
    
    利用Agno原生的SqliteDb实现：
    - 会话持久化
    - 状态共享
    - 历史记录续接
    """
    
    def __init__(self, db_path: str = "tmp/agents.db"):
        """
        初始化会话管理器
        
        Args:
            db_path: 数据库文件路径
        """
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # SqliteDb实例
        self.db = SqliteDb(db_file=db_path)
        
        # 当前Agent实例
        self._agent: Optional[Agent] = None
    
    @property
    def agent(self) -> Agent:
        """获取当前Agent实例"""
        if self._agent is None:
            raise ValueError("Agent未初始化，请先调用get_agent()")
        return self._agent
    
    def get_agent(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        enable_memory: bool = False,
        debug_mode: bool = False
    ) -> Agent:
        """
        创建/获取Agent实例
        
        Args:
            user_id: 用户ID
            session_id: 会话ID（不提供则自动创建）
            enable_memory: 是否启用记忆系统
            debug_mode: 是否启用调试模式
        
        Returns:
            Agent实例
        """
        from agent.core.agent import create_agent
        
        self._agent = create_agent(
            user_id=user_id,
            session_id=session_id,
            enable_memory=enable_memory,
            debug_mode=debug_mode
        )
        
        # 初始化会话状态
        self._init_session_state()
        
        return self._agent
    
    def _init_session_state(self):
        """初始化会话状态"""
        if self._agent is not None:
            # 初始化session_state
            self._agent.session_state = {
                "uploaded_file": None,      # 上传的文件内容
                "decoded_data": None,        # 解码后的数据
                "mapping_table": None,       # 字段映射表
                "threat_mapping": None,      # 威胁类型映射表
                "processing_status": "idle", # 处理状态：idle/processing/completed
                "last_update": None         # 最后更新时间
            }
    
    def update_state(self, key: str, value: Any):
        """
        更新会话状态
        
        Args:
            key: 状态键
            value: 状态值
        """
        if self._agent is not None and self._agent.session_state is not None:
            self._agent.session_state[key] = value
            self._agent.session_state["last_update"] = self._get_timestamp()
    
    def get_state(self, key: str) -> Any:
        """
        获取会话状态
        
        Args:
            key: 状态键
        
        Returns:
            状态值
        """
        if self._agent is not None and self._agent.session_state is not None:
            return self._agent.session_state.get(key)
        return None
    
    def clear_state(self):
        """清空会话状态"""
        if self._agent is not None:
            self._init_session_state()
    
    @staticmethod
    def _get_timestamp() -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_session_history(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        num_runs: int = 5
    ) -> list:
        """
        获取会话历史
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            num_runs: 返回的运行次数
        
        Returns:
            历史记录列表
        """
        # 这个方法需要通过Agent的db来查询
        # 简化实现，实际使用中可以通过db查询
        return []
    
    def set_processing_status(self, status: str):
        """
        设置处理状态
        
        Args:
            status: 状态值
                - idle: 空闲
                - processing: 处理中
                - completed: 完成
                - error: 错误
        """
        valid_statuses = ["idle", "processing", "completed", "error"]
        if status not in valid_statuses:
            raise ValueError(f"无效状态，可选值: {valid_statuses}")
        
        self.update_state("processing_status", status)
    
    def get_processing_status(self) -> str:
        """获取当前处理状态"""
        return self.get_state("processing_status") or "idle"


# 全局会话管理器实例
_global_session_manager: Optional[SessionManager] = None


def get_session_manager(db_path: str = "tmp/agents.db") -> SessionManager:
    """
    获取全局会话管理器实例
    
    Args:
        db_path: 数据库文件路径
    
    Returns:
        SessionManager实例
    """
    global _global_session_manager
    
    if _global_session_manager is None:
        _global_session_manager = SessionManager(db_path)
    
    return _global_session_manager


def init_agent(
    user_id: str,
    session_id: Optional[str] = None
) -> Agent:
    """
    初始化Agent的便捷函数
    
    Args:
        user_id: 用户ID
        session_id: 会话ID
    
    Returns:
        Agent实例
    """
    manager = get_session_manager()
    return manager.get_agent(user_id, session_id)
