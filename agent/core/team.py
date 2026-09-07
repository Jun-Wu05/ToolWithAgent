"""专业 Agent 注册表。

自然语言理解只由独立 PlannerAgent 负责；本模块创建字段映射、威胁映射、
枚举处理和日志解析 Agent，并以不可路由的注册表提供给执行适配器。
"""

from dataclasses import dataclass
from typing import List, Optional

from pydantic import BaseModel

from agno.agent import Agent

from agent.core.model_config import ModelConfig
from agent.prompts import load_field_weak_prompt, load_threat_type_prompt, load_enum_field_prompt
from agent.tools import (
    enum_field_tool,
    extract_enum_from_logs,
    extract_enum_with_regex,
    identify_log_format,
    classify_log_features,
)


# ============= 加载原始提示词 =============

def _load_prompts() -> dict:
    """加载所有提示词"""
    return {
        "field": load_field_weak_prompt(),
        "threat": load_threat_type_prompt(),
        "enum": load_enum_field_prompt(),
    }


# ============= 字段映射 Agent =============

def _get_field_mapping_instructions() -> str:
    """获取字段映射Agent指令（标准字段候选已由系统预检索注入，Agent 无需调用查询工具）"""
    prompts = _load_prompts()

    return f"""你是网络安全日志标准化专家。

{prompts['field']}

## 字段匹配策略
- **标准字段候选已由系统预检索并注入到输入中**（"## 标准字段候选"部分），直接使用
- 无需调用任何标准字段查询工具，候选已在输入中提供
- 匹配方式：对每个原始字段，在候选列表中按相似度排序选取最佳匹配的系统属性名称
- 若某字段无候选或候选不匹配，根据字段名的英文语义直接映射（如 srcAddress→源地址, destPort→目的端口）

## 工作原则
- **用户消息中已包含所有可用数据**（字段列表 + 候选 + 日志样本/解码数据），请直接使用
- 当日志样本或解码数据包含字段值时，优先根据字段值和字段名语义进行匹配
- 当仅有字段名时，根据候选相似度排序选择最佳匹配
- **禁止**输出"请提供原始日志"、"需要更多数据"等索取性回复
- **禁止调用任何工具**；直接按 `output_schema` 返回本批字段的结构化映射
- **严禁调用任何标准字段查询函数**

注意：
- 必须严格按照上述规则输出
- **只输出 JSON 数组格式的映射结果**，不输出解释、分析、过程或备注
- JSON 格式必须严格遵循以下两种情形之一：
  - 匹配成功：`[{{"原始字段名": "xxx", "系统属性名称": "yyy", "匹配状态": "匹配成功"}}]`
  - 未匹配：`[{{"原始字段名": "xxx", "系统属性名称": "未匹配", "匹配状态": "未匹配"}}]`
- ⚠️ 联动约束：当"系统属性名称"为"未匹配"时，"匹配状态"必须同时为"未匹配"，两者一致
- 只能使用标准字段表中的中文系统属性名称
"""


# ============= 结构化输出模型 =============

class ThreatMappingItem(BaseModel):
    """威胁类型单条映射"""
    mappingType: str = "REGULAR"
    orgValue: str
    mappingValue: str

class ThreatMappingList(BaseModel):
    """威胁类型映射列表（Agno output_schema 要求 BaseModel 包装）"""
    items: List[ThreatMappingItem]


# ============= 字段映射结构化输出模型 =============

class FieldMappingItem(BaseModel):
    """字段映射单条记录"""
    原始字段名: str
    系统属性名称: str
    匹配状态: str  # "匹配成功" | "未匹配"

class FieldMappingList(BaseModel):
    """字段映射列表（Agno output_schema 要求 BaseModel 包装）"""
    items: List[FieldMappingItem]


# ============= 威胁映射 Agent =============

def _get_threat_instructions() -> str:
    """获取威胁类型Agent指令"""
    prompts = _load_prompts()

    # 直接引用 threat_type.md
    return f"""You are a threat alert to standard classification mapper.

{prompts['threat']}

注意：
- 必须严格按照上述规则输出
"""


# ============= 枚举处理 Agent =============

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
    """创建纯结构化字段映射 Agent；字段回写由执行适配器负责。"""
    return Agent(
        name="FieldMappingAgent",
        role="字段映射专家",
        model=ModelConfig.get_main_model(),
        instructions=_get_field_mapping_instructions(),
        output_schema=FieldMappingList,   # v4: API 层强制输出 JSON 且符合 schema，杜绝非规范格式
        markdown=False,                   # v4: 配合 output_schema JSON 输出，禁止 Markdown 包装
        debug_mode=False,
    )


def create_threat_agent() -> Agent:
    """创建威胁类型Agent（纯 prompt 驱动，无需工具）"""
    return Agent(
        name="ThreatAgent",
        role="威胁类型专家",
        model=ModelConfig.get_main_model(),
        instructions=_get_threat_instructions(),
        output_schema=ThreatMappingList,  # v3: API 层强制输出 JSON 且符合 schema，杜绝非规范格式
        markdown=False,                   # 配合 output_schema JSON 输出，禁止 Markdown 包装
        debug_mode=False,
    )


def create_enum_agent() -> Agent:
    """创建枚举Agent（挂载工具：enum_field_tool, extract_enum_from_logs, extract_enum_with_regex）"""
    return Agent(
        name="EnumAgent",
        role="枚举字段专家",
        model=ModelConfig.get_main_model(),
        instructions=_get_enum_instructions(),
        tools=[
            enum_field_tool,              # 提取可枚举字段
            extract_enum_from_logs,       # 从日志中提取枚举值
            extract_enum_with_regex,      # 正则提取枚举值（返回值含所有枚举数据，生成下载文件由 Web 层完成）
        ],
        tool_call_limit=3,                # v2: 3 个工具，3 次足够
        markdown=True,
        debug_mode=False,
    )


# ============= 日志解析 Agent =============

def _get_log_parser_instructions() -> str:
    """获取日志解析Agent指令"""
    return """你是日志格式识别与字段特征提取专家。

## 任务流程
1. 使用 `identify_log_format` 识别日志格式（json/kv/space/semicolon/comma）
2. 根据识别结果判断是否需要分类：
   - 若为 JSON 或 KV 格式，字段名已明确，可跳过分类
   - 若为 space/semicolon/comma 格式，使用 `classify_log_features` 推断字段名和类型

## 输出要求
- 输出 JSON 格式的字段列表和特征分类结果
- 包含每个字段的名称、类型、别名、位置、样本值
- 不要输出解释性文字，直接输出结果

## 约束
- 只做格式识别和字段提取，不修改原始日志
- 不做威胁分析、枚举提取、字段映射
- 工具中已包含 LLM 调用，你只需调工具即可"""


def create_log_parser_agent() -> Agent:
    """创建日志解析Agent（挂载工具：identify_log_format, classify_log_features）

    设计意图：工具内部通过 httpx 直调 LLM，不经 Agno 路由循环，省 40-60s。
    """
    return Agent(
        name="LogParserAgent",
        role="日志格式识别与字段提取专家",
        model=ModelConfig.get_main_model(),
        instructions=_get_log_parser_instructions(),
        tools=[
            identify_log_format,           # Step 1: 格式识别（工具内调 LLM）
            classify_log_features,         # Step 2: 特征分类（工具内调 LLM）
        ],
        tool_call_limit=2,                 # 2 个工具，2 次足够
        markdown=True,
        debug_mode=False,
    )


# ============= 创建专业 Agent 注册表 =============


@dataclass(frozen=True)
class ProfessionalAgentRegistry:
    """保存可由执行适配器按名称选择的专业 Agent，不提供自主路由能力。"""

    members: tuple[Agent, ...]


def create_data_mapping_team() -> ProfessionalAgentRegistry:
    """创建专业 Agent 注册表；缺少密钥时由模型构造层抛出带变量名的错误。

    返回值：
        仅含专业 Agent 成员的不可变注册表。

    不变量：
        注册表不提供 run 或路由指令，用户意图只能由 PlannerAgent 理解。
    """
    return ProfessionalAgentRegistry(
        members=(
            create_field_mapping_agent(),
            create_threat_agent(),
            create_enum_agent(),
            create_log_parser_agent(),
        )
    )
