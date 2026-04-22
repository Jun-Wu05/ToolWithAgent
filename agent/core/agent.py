"""
Agent主入口

基于Agno的智能Agent实现
整合会话管理、历史记录、多模型策略、业务工具
"""

import os
from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.siliconflow import Siliconflow

from agent.core.model_config import ModelConfig
from agent.core.prompts import load_system_prompt

# 导入业务工具
from agent.tools.base64_tool import base64_decode_tool, base64_encode_tool
from agent.tools.standard_mapper import field_mapping_tool, generate_mapping_table_tool
from agent.tools.threat_type_tool import threat_type_tool, apply_threat_mapping_tool
from agent.tools.enum_field_tool import enum_field_tool, apply_enum_mapping_tool


def create_agent(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_memory: bool = False,
    debug_mode: bool = False
) -> Agent:
    """
    创建主Agent实例
    
    这是项目的核心Agent，具备以下能力：
    - 会话持久化（SqliteDb）
    - 历史记录（add_history_to_context）
    - 意图理解
    - 任务规划
    - 工具调用
    - 状态管理
    - 业务工具整合
    
    Args:
        user_id: 用户ID，用于区分不同用户
        session_id: 会话ID，不提供则自动创建
        enable_memory: 是否启用记忆系统（后续功能）
        debug_mode: 是否启用调试模式
    
    Returns:
        Agent实例
    """
    # 数据库配置
    db_path = os.path.join(os.getcwd(), "tmp", "agents.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # 获取API Key
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    
    # 加载系统提示词
    instructions = load_system_prompt()
    
    # 创建Agent，配置所有业务工具
    agent = Agent(
        # 模型配置
        model=Siliconflow(
            id=ModelConfig.MAIN_MODEL,
            api_key=api_key
        ),
        
        # 基本信息
        name="数据映射助手",
        description="安全设备配置规则字段映射智能助手",
        
        # 会话管理 ⭐
        db=SqliteDb(db_file=db_path),
        user_id=user_id,
        session_id=session_id,
        
        # 历史记录 ⭐
        add_history_to_context=True,
        num_history_runs=5,
        
        # 指令
        instructions=instructions,
        
        # 输出格式
        markdown=True,
        debug_mode=debug_mode,
        
        # 业务工具 ⭐
        tools=[
            # Base64工具
            base64_decode_tool,
            base64_encode_tool,
            
            # 字段映射工具
            field_mapping_tool,
            generate_mapping_table_tool,
            
            # 威胁类型工具
            threat_type_tool,
            apply_threat_mapping_tool,
            
            # 枚举字段工具
            enum_field_tool,
            apply_enum_mapping_tool,
        ],
    )
    
    return agent


def create_simple_agent(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Agent:
    """
    创建简单任务Agent
    
    用于处理简单的数据转换任务：
    - Base64解码
    - 字段提取
    - 简单编码
    
    Args:
        user_id: 用户ID
        session_id: 会话ID
    
    Returns:
        简单任务Agent实例
    """
    db_path = os.path.join(os.getcwd(), "tmp", "agents.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    
    return Agent(
        model=Siliconflow(
            id=ModelConfig.SIMPLE_MODEL,
            api_key=api_key
        ),
        
        name="SimpleAgent",
        description="处理简单的数据转换任务",
        
        # 会话管理
        db=SqliteDb(db_file=db_path),
        user_id=user_id,
        session_id=session_id,
        
        # 历史记录
        add_history_to_context=True,
        num_history_runs=3,
        
        # 简单任务不需要复杂提示
        instructions="""
你是一个简单任务助手，负责：
1. Base64解码 - 将Base64字符串解码为原始数据
2. 字段提取 - 从数据中提取字段
3. 简单编码 - 将数据编码为Base64

保持简单直接，执行任务后返回结果。
""",
        
        markdown=True,
        debug_mode=False,
    )


def create_complex_agent(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Agent:
    """
    创建复杂推理Agent
    
    用于处理需要推理的复杂任务：
    - 字段映射
    - 威胁类型标准化
    - 枚举处理
    
    Args:
        user_id: 用户ID
        session_id: 会话ID
    
    Returns:
        复杂推理Agent实例
    """
    db_path = os.path.join(os.getcwd(), "tmp", "agents.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    
    return Agent(
        model=Siliconflow(
            id=ModelConfig.COMPLEX_MODEL,
            api_key=api_key
        ),
        
        name="ComplexAgent",
        description="处理需要推理的复杂任务",
        
        # 会话管理
        db=SqliteDb(db_file=db_path),
        user_id=user_id,
        session_id=session_id,
        
        # 历史记录
        add_history_to_context=True,
        num_history_runs=5,
        
        # 复杂任务需要详细指令
        instructions="""
你是一个复杂推理助手，负责：

## 1. 字段映射
- 根据标准字段表，生成字段映射表
- 支持弱匹配（模糊匹配）和强匹配（精确匹配）
- 输出格式：[{原始字段: xxx, 标准字段: xxx, 匹配度: 高/中/低}]

## 2. 威胁类型标准化
- 将原始威胁类型映射到标准值
- 使用威胁类型枚举
- 处理特殊情况

## 3. 枚举处理
- 处理mappingType字段
- 原始值到映射值的转换

## 标准字段表
使用标准字段表中的中文名称作为标准字段。

## 约束
1. 只使用标准字段，禁止自造字段名
2. 清晰展示映射过程和结果
3. 关键决策交给用户确认
""",
        
        markdown=True,
        debug_mode=False,
    )


def route_task(task: str) -> str:
    """
    任务路由 - 根据任务类型选择合适的Agent
    
    Args:
        task: 任务描述
    
    Returns:
        Agent类型：'simple', 'complex', 'main'
    """
    task_lower = task.lower()
    
    # 简单任务
    if any(keyword in task_lower for keyword in ['解码', '编码', 'base64', 'decode', 'encode']):
        if '映射' not in task_lower and '威胁' not in task_lower:
            return 'simple'
    
    # 复杂任务
    if any(keyword in task_lower for keyword in ['映射', '威胁', '标准化', '枚举']):
        return 'complex'
    
    # 默认主Agent
    return 'main'


def create_routed_agent(
    task: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Agent:
    """
    根据任务类型创建合适的Agent
    
    Args:
        task: 任务描述
        user_id: 用户ID
        session_id: 会话ID
    
    Returns:
        适合处理该任务的Agent
    """
    agent_type = route_task(task)
    
    if agent_type == 'simple':
        return create_simple_agent(user_id, session_id)
    elif agent_type == 'complex':
        return create_complex_agent(user_id, session_id)
    else:
        return create_agent(user_id, session_id)
