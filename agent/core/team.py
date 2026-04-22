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
from agent.prompts import load_field_weak_prompt, load_threat_type_prompt, load_enum_field_prompt
from agent.prompts import load_standard_fields
import json


def _load_threat_config() -> str:
    """加载威胁类型配置"""
    from pathlib import Path
    config_path = Path(__file__).parent.parent.parent / "config" / "threat_type_config.json"
    if config_path.exists():
        return config_path.read_text(encoding='utf-8')
    return ""


# ============= 加载原始提示词 =============

def _load_prompts() -> dict:
    """加载所有提示词"""
    return {
        "field": load_field_weak_prompt(),
        "threat": load_threat_type_prompt(),
        "enum": load_enum_field_prompt(),
    }


def _load_standard_fields_list() -> str:
    """加载标准字段表"""
    return load_standard_fields()


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

def _get_field_mapping_instructions() -> str:
    """获取字段映射Agent指令"""
    prompts = _load_prompts()
    standard_fields = _load_standard_fields_list()
    
    return f"""你是网络安全日志标准化专家。

{prompts['field']}

## 标准字段表（必须严格使用以下中文名称）
```
{standard_fields}
```

注意：
- 必须严格按照上述规则输出
- 只输出Markdown表格，不输出其他内容
- 只能使用标准字段表中的中文系统属性名称
"""


# ============= ThreatAgent =============

def _get_threat_instructions() -> str:
    """获取威胁类型Agent指令"""
    prompts = _load_prompts()
    threat_config = _load_threat_config()
    
    # 提取威胁类型名称列表
    threat_names = []
    if threat_config:
        try:
            config = json.loads(threat_config)
            threat_names = [t["name"] for t in config.get("threat_types", [])]
        except Exception:
            pass
    
    threat_list = "、".join(threat_names) if threat_names else "见配置文件"
    
    return f"""You are a threat alert to standard classification mapper.

{prompts['threat']}

## 威胁类型配置（完整）
{threat_config[:8000] if threat_config else "配置加载失败"}

注意：
- 必须严格按照上述规则输出
- mappingValue必须从配置中的threat_types列表选择
- 只输出Markdown表格，不输出其他内容
"""


# ============= EnumAgent =============

def _get_enum_instructions() -> str:
    """获取枚举Agent指令"""
    prompts = _load_prompts()
    return f"""你是网络安全设备配置规则枚举字段处理专家。

{prompts['enum']}

注意：
- 必须严格按照上述规则执行
- 枚举值必须精确匹配
"""


# ============= 创建专业Agent =============

def create_field_mapping_agent() -> Agent:
    """创建字段映射Agent"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    return Agent(
        name="FieldMappingAgent",
        role="字段映射专家",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        instructions=_get_field_mapping_instructions(),
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
        instructions=_get_threat_instructions(),
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
        instructions=_get_enum_instructions(),
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
