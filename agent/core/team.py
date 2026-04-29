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
from agent.prompts import load_field_weak_prompt, load_threat_type_prompt, load_enum_field_prompt, load_router_prompt
from agent.prompts import load_standard_fields
from agent.tools import (
    base64_decode_tool,
    field_mapping_tool,
    generate_mapping_table_tool,
    threat_type_tool,
    enum_field_tool,
    extract_enum_from_logs,
    extract_enum_with_regex,
    get_enum_as_json_file,
    get_enum_as_mapping_file,
)


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


# ============= 路由指令（从 router.md 加载）=============

def _load_router_instructions() -> str:
    """加载 Team Router 路由指令"""
    return load_router_prompt()


# ============= FieldMappingAgent =============

def _get_field_mapping_instructions() -> str:
    """获取字段映射Agent指令"""
    prompts = _load_prompts()
    standard_fields = _load_standard_fields_list()
    
    return f"""你是网络安全日志标准化专家。

{prompts['field']}

## 标准字段表（参考字典 — 匹配时按需查询，无需逐条记忆）
```
{standard_fields}
```

## 字段匹配策略
- 将标准字段表视为参考字典，仅当需要匹配某字段时才在表中查找
- 匹配方式：将用户字段名与标准字段表逐行对比，取最相似的中文系统属性名称
- **禁止**：试图理解或记忆全部标准字段，只关注当前需要匹配的字段

注意：
- 必须严格按照上述规则输出
- **只输出 JSON 数组格式的映射结果**，不输出解释、分析、过程或备注
- JSON 格式必须为：`[{{"原始字段名": "xxx", "系统属性名称": "yyy", "匹配状态": "匹配成功"}}]`
- 只能使用标准字段表中的中文系统属性名称
"""


# ============= ThreatAgent =============

def _get_threat_instructions() -> str:
    """获取威胁类型Agent指令"""
    prompts = _load_prompts()
    
    # 直接引用 threat_type.md
    return f"""You are a threat alert to standard classification mapper.

{prompts['threat']}

注意：
- 必须严格按照上述规则输出
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
    """创建字段映射Agent（挂载工具：field_mapping, generate_mapping_table, base64_decode）"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    return Agent(
        name="FieldMappingAgent",
        role="字段映射专家",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        instructions=_get_field_mapping_instructions(),
        tools=[
            field_mapping_tool,            # 单字段标准化映射（编辑距离算法）
            generate_mapping_table_tool,   # 批量生成映射表
            base64_decode_tool,            # Base64 解码（输入常为 Base64 编码）
        ],
        markdown=True,
        debug_mode=False,
    )


def create_threat_agent() -> Agent:
    """创建威胁类型Agent（挂载工具：threat_type_tool, base64_decode）"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    return Agent(
        name="ThreatAgent",
        role="威胁类型专家",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        instructions=_get_threat_instructions(),
        tools=[
            threat_type_tool,     # 威胁类型规则匹配 + 置信度评分
            base64_decode_tool,   # Base64 解码输入
        ],
        markdown=True,
        debug_mode=False,
    )


def create_enum_agent() -> Agent:
    """创建枚举Agent（挂载工具：enum_field_tool, extract_enum_from_logs, extract_enum_with_regex, get_enum_as_json_file, get_enum_as_mapping_file, base64_decode）"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    return Agent(
        name="EnumAgent",
        role="枚举字段专家",
        model=Siliconflow(id=ModelConfig.MAIN_MODEL, api_key=api_key),
        instructions=_get_enum_instructions(),
        tools=[
            enum_field_tool,              # 提取可枚举字段
            extract_enum_from_logs,       # 从日志中提取枚举值
            extract_enum_with_regex,      # 正则提取枚举值
            get_enum_as_json_file,        # 导出枚举为 JSON 文件
            get_enum_as_mapping_file,     # 导出枚举为映射表文件
            base64_decode_tool,           # Base64 解码输入
        ],
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
    
    # 调试模式通过环境变量控制，默认生产环境关闭
    _debug = os.getenv("AGNO_DEBUG_MODE", "false").lower() == "true"
    _show_members = os.getenv("AGNO_SHOW_MEMBERS", "false").lower() == "true"

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
        instructions=_load_router_instructions(),
        markdown=True,
        debug_mode=_debug,
        show_members_responses=_show_members,
    )
    
    return team


# ============= Team 单例缓存 =============

_team_instance: Optional[Team] = None
"""模块级 Team 单例缓存，避免每次调用重建 Agent 和加载指令"""


def get_team_instance() -> Team:
    """
    获取 Team 单例（用于 Web 应用），首次调用创建，后续调用返回缓存实例。

    Returns:
        Team 实例（单例）
    """
    global _team_instance
    if _team_instance is None:
        _team_instance = create_data_mapping_team()
    return _team_instance


def reset_team_instance() -> None:
    """
    重置 Team 单例（用于测试或需要重建的场景）。
    注意：调用后下次 get_team_instance() 会重新创建。
    """
    global _team_instance
    _team_instance = None
