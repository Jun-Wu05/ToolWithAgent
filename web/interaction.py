# -*- coding: utf-8 -*-
"""交互优化模块 - 快捷键、操作历史、批量处理"""

from __future__ import annotations
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
import streamlit as st


@dataclass
class ActionRecord:
    """操作记录"""
    action_type: str  # 操作类型
    description: str  # 操作描述
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict = field(default_factory=dict)  # 额外数据
    success: bool = True  # 是否成功


class ActionHistory:
    """操作历史管理器"""
    
    MAX_HISTORY = 50  # 最多保存50条记录
    
    def __init__(self):
        if "action_history" not in st.session_state:
            st.session_state.action_history = []
    
    def add(self, action_type: str, description: str, data: dict = None, success: bool = True):
        """添加操作记录"""
        record = ActionRecord(
            action_type=action_type,
            description=description,
            data=data or {},
            success=success
        )
        st.session_state.action_history.append(record)
        
        # 限制历史长度
        if len(st.session_state.action_history) > self.MAX_HISTORY:
            st.session_state.action_history = st.session_state.action_history[-self.MAX_HISTORY:]
    
    def get_all(self) -> list:
        """获取所有历史记录"""
        return st.session_state.action_history
    
    def get_by_type(self, action_type: str) -> list:
        """获取指定类型的记录"""
        return [r for r in st.session_state.action_history if r.action_type == action_type]
    
    def clear(self):
        """清空历史"""
        st.session_state.action_history = []
    
    def get_summary(self) -> str:
        """获取历史摘要"""
        if not st.session_state.action_history:
            return "暂无操作历史"
        
        lines = ["**操作历史：**\n"]
        for i, record in enumerate(reversed(st.session_state.action_history[-10:]), 1):
            status = "✅" if record.success else "❌"
            time_str = record.timestamp.strftime("%H:%M:%S")
            lines.append(f"{i}. {status} [{time_str}] {record.description}")
        
        return "\n".join(lines)


def init_interaction_state():
    """初始化交互相关的 session state"""
    if "action_history" not in st.session_state:
        st.session_state.action_history = []
    
    if "batch_mode" not in st.session_state:
        st.session_state.batch_mode = False
    
    if "batch_files" not in st.session_state:
        st.session_state.batch_files = []
    
    if "current_action_index" not in st.session_state:
        st.session_state.current_action_index = -1


def add_action(action_type: str, description: str, data: dict = None, success: bool = True):
    """快捷添加操作记录"""
    history = ActionHistory()
    history.add(action_type, description, data, success)


def get_action_history() -> ActionHistory:
    """获取操作历史管理器"""
    return ActionHistory()


# 快捷键定义
KEYBOARD_SHORTCUTS = {
    "Ctrl+1": "标准字段处理",
    "Ctrl+2": "枚举字段处理", 
    "Ctrl+3": "威胁类型处理",
    "Ctrl+Enter": "确认映射",
    "Ctrl+D": "下载结果",
    "Escape": "取消/关闭",
}


def get_shortcuts_html() -> str:
    """获取快捷键帮助 HTML"""
    shortcuts = [
        ("Ctrl + 1", "标准字段处理"),
        ("Ctrl + 2", "枚举字段处理"),
        ("Ctrl + 3", "威胁类型处理"),
        ("Ctrl + Enter", "确认映射"),
        ("Ctrl + D", "下载结果"),
    ]
    
    lines = ["**⌨️ 快捷键**\n"]
    for key, desc in shortcuts:
        lines.append(f"- `{key}` - {desc}")
    
    return "\n".join(lines)
