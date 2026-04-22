"""
Agno Team 配置 - 多Agent架构

使用 Agno Team Route 模式实现：
- RouterAgent: 意图理解、任务路由
- FieldMappingAgent: 字段映射
- ThreatAgent: 威胁类型标准化
- EnumAgent: 枚举处理

Route 模式：Team Leader 路由到单个 MemberAgent，直接返回结果
"""

import os
from typing import Optional
from agno.agent import Agent
from agno.models.siliconflow import Siliconflow
from agno.team.team import Team
from agno.team.mode import TeamMode

from agent.core.model_config import ModelConfig


# ============= 路由指令 =============

ROUTER_INSTRUCTIONS = """你是任务路由专家。

根据用户请求中的关键词，将任务路由到对应的专业Agent：

1. 包含"映射"、"字段"、"map" → 路由到 FieldMappingAgent
2. 包含"威胁"、"threat"、"攻击" → 路由到 ThreatAgent
3. 包含"枚举"、"enum" → 路由到 EnumAgent
4. 其他请求 → 根据意图判断或直接回答

路由规则：
- 只做路由，不执行任务
- 精确匹配关键词，避免误路由
- 如果请求模糊，询问用户意图
"""


# ============= FieldMappingAgent =============

FIELD_MAPPING_INSTRUCTIONS = """你是字段映射专家。

你的职责是将原始日志字段映射到标准字段表。

输入数据：
- decoded_json: 解码后的 JSON 对象
- fields: 提取的字段列表

处理流程：
1. 分析原始字段名
2. 根据标准字段表（config/对象.xlsx）进行匹配
3. 生成映射表（Markdown表格格式）

输出格式：
| 原始字段 | 标准字段 | 匹配度 | 说明 |
|---------|---------|-------|------|
| xxx | xxx | 高/中/低 | - |

注意：
- 匹配度根据字段名相似度判断
- 只输出映射表，不要其他解释
- 标准字段参考 config/对象.xlsx
"""


# ============= ThreatAgent =============

THREAT_INSTRUCTIONS = """你是威胁类型专家。

你的职责是识别和标准化日志中的威胁类型。

输入数据：
- decoded_json: 解码后的 JSON 对象

处理流程：
1. 识别所有威胁相关字段
2. 匹配标准威胁类型（参考 config/threat_type_config.json）
3. 生成威胁映射表

输出格式：
| 原始字段 | 原始值 | 标准威胁类型 | 说明 |
|---------|--------|-------------|------|
| xxx | xxx | xxx | - |

标准威胁类型：
- 网络攻击类：SQL注入、XSS、CSRF、webshell等
- 恶意软件类：病毒、木马、蠕虫、勒索等
- 异常行为类：暴力破解、扫描探测、权限提升等
"""


# ============= EnumAgent =============

ENUM_INSTRUCTIONS = """你是枚举字段专家。

你的职责是处理和标准化字段枚举值。

输入数据：
- decoded_json: 解码后的 JSON 对象
- fields: 字段列表

处理流程：
1. 识别枚举类型字段
2. 提取枚举值
3. 生成枚举映射表

输出格式：
| 字段名 | 原始枚举值 | 标准枚举值 | 说明 |
|--------|-----------|-----------|------|
| xxx | xxx | xxx | - |

注意：
- 枚举值必须精确匹配
- 不确定时标记为"待确认"
"""


# ============= 创建专业Agent =============

def create_field_mapping_agent() -> Agent:
    """创建字段映射Agent"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    return Agent(
        name="FieldMappingAgent",
        role="字段映射专家",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        instructions=FIELD_MAPPING_INSTRUCTIONS,
        markdown=True,
        debug_mode=False,
    )


def create_threat_agent() -> Agent:
    """创建威胁类型Agent"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    return Agent(
        name="ThreatAgent",
        role="威胁类型专家",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        instructions=THREAT_INSTRUCTIONS,
        markdown=True,
        debug_mode=False,
    )


def create_enum_agent() -> Agent:
    """创建枚举Agent"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    return Agent(
        name="EnumAgent",
        role="枚举字段专家",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        instructions=ENUM_INSTRUCTIONS,
        markdown=True,
        debug_mode=False,
    )


# ============= 创建Team =============

def create_data_mapping_team() -> Team:
    """
    创建数据映射Team
    
    使用 Route 模式：
    - Team Leader 做路由
    - 路由到对应 MemberAgent
    - MemberAgent 直接返回结果
    
    Returns:
        Team实例
    """
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    
    # 创建专业Agent
    field_mapping_agent = create_field_mapping_agent()
    threat_agent = create_threat_agent()
    enum_agent = create_enum_agent()
    
    # 创建Team
    team = Team(
        name="DataMappingTeam",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        mode=TeamMode.route,  # 路由模式
        members=[
            field_mapping_agent,
            threat_agent,
            enum_agent,
        ],
        instructions=ROUTER_INSTRUCTIONS,
        markdown=True,
        debug_mode=False,
        show_members_responses=True,  # 显示MemberAgent的响应
    )
    
    return team


def get_team_instance() -> Team:
    """
    获取Team单例（用于Web应用）
    
    Returns:
        Team实例
    """
    return create_data_mapping_team()
