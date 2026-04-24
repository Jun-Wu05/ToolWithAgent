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

ROUTER_INSTRUCTIONS = """你是数据映射智能助手。

你可以处理以下任务：
1. 字段映射 - 用户说"映射"、"字段"、"标准字段"、"字段处理"、"字段标准化"时
2. 威胁类型处理 - 用户说"威胁类型"、"threat_type"时
3. 枚举处理 - 用户说"枚举"、"enum"时

当用户输入以以下标签开头时，直接路由到对应Agent：
- [字段映射] → FieldMappingAgent
- [威胁类型] → ThreatAgent  
- [枚举处理] → EnumAgent

当用户发送以下内容时，都应路由到字段映射：
- "标准字段处理"、"字段标准化"、"字段标准化处理"
- "帮我进行标准字段处理"
- "进行字段映射"

当用户发送"映射"、"威胁"、"枚举"等关键词时：
- 直接调用对应的专业Agent执行任务
- 将上下文数据（字段列表、数据预览）一并传递
- 返回Agent的处理结果

注意：
- 不要只做路由，要实际执行任务
- 使用Agent的工具和提示词处理
- 返回完整的处理结果
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
    import time
    from src.logger import get_logger
    
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    logger = get_logger("team")
    
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
        debug_mode=True,  # 启用 debug 模式
        show_members_responses=True,  # 显示MemberAgent的响应
    )
    
    # 包装 run 方法添加日志
    original_run = team.run
    
    async def logged_run(message: str):
        logger.info(f"[TEAM] 开始处理消息，长度: {len(message)}")
        start_time = time.time()
        
        result = await original_run(message)
        
        duration = time.time() - start_time
        logger.info(f"[TEAM] 处理完成，耗时: {duration:.2f}秒")
        
        # 记录输出
        content = result.content if hasattr(result, 'content') else str(result)
        logger.info(f"[TEAM] 输出长度: {len(content)} 字符")
        
        # 记录 tokens
        if hasattr(result, 'usage') and result.usage:
            usage = result.usage
            input_tokens = getattr(usage, 'input_tokens', 'N/A')
            output_tokens = getattr(usage, 'output_tokens', 'N/A')
            logger.info(f"[TEAM] Tokens - 输入: {input_tokens}, 输出: {output_tokens}")
        
        return result
    
    team.run = logged_run
    
    return team


def get_team_instance() -> Team:
    """
    获取Team单例（用于Web应用）
    
    Returns:
        Team实例
    """
    return create_data_mapping_team()
