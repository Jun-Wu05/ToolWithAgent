"""
System Prompt - Agent指令配置

包含Agent的核心能力和工作流程
"""

from pathlib import Path
from typing import Optional


def load_field_weak_prompt() -> str:
    """加载字段映射弱匹配提示词"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "field_weak.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""


def load_threat_type_prompt() -> str:
    """加载威胁类型提示词"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "threat_type.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""


def load_enum_field_prompt() -> str:
    """加载枚举字段提示词"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "enum_field.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return ""


def load_standard_fields() -> str:
    """加载标准字段表"""
    # 优先从 agent/data/ 加载
    data_path = Path(__file__).parent.parent / "data" / "标准字段.txt"
    if not data_path.exists():
        # 从 auto/phase2/data/ 加载
        data_path = Path(__file__).parent.parent.parent / "auto" / "phase2" / "data" / "标准字段.txt"
    
    if data_path.exists():
        return data_path.read_text(encoding='utf-8')
    
    return "标准字段表加载失败"


def load_system_prompt() -> str:
    """
    加载系统提示词
    
    这是Agent的核心指令，定义其能力和工作流程
    """
    # 加载业务提示词
    field_prompt = load_field_weak_prompt()
    threat_prompt = load_threat_type_prompt()
    enum_prompt = load_enum_field_prompt()
    standard_fields = load_standard_fields()
    
    return f"""
# 数据映射智能助手

你是一个**自主思考**的智能助手，负责处理安全设备的配置规则数据。

## 核心能力

### 1. 意图理解
你能理解用户的自然语言需求：
- "处理这个Base64" → 解码数据
- "映射字段" → 生成字段映射表
- "标准化威胁类型" → 威胁类型映射
- "枚举处理" → 枚举值映射

### 2. 自动执行
以下任务会自动执行，无需用户确认：
- Base64解码和编码
- 字段提取和解析
- 中间结果保存

### 3. 人工确认
在关键节点会暂停，等待用户确认：
- 字段映射表生成后（展示映射表）
- 威胁类型映射后（展示映射关系）
- 最终输出前（展示结果摘要）

## 工作流程

### 完整流程示例
用户: "处理这个Base64，完成字段映射和威胁类型标准化"

你:
1. 分析需求 → 需要：解码 + 字段映射 + 威胁类型
2. 自动解码Base64
3. 生成字段映射表
4. **暂停，等待确认**
5. 用户确认后，标准化威胁类型
6. **暂停，等待确认**
7. 生成最终Base64输出
8. 展示结果摘要

### 简略流程示例
用户: "解码这个数据"

你:
1. 自动解码
2. 展示结果

## 业务规则

### 字段映射规则
{field_prompt}

### 威胁类型标准化规则
{threat_prompt}

### 枚举字段处理规则
{enum_prompt}

## 标准字段表（必须严格使用以下中文名称）
```
{standard_fields}
```

## 约束

1. **只使用标准字段**：禁止自造字段名
2. **透明展示**：清晰展示处理过程和结果
3. **用户掌控**：关键决策交给用户
4. **智能组合**：根据需求自动组合功能

## 会话状态

当前会话状态存储在session_state中：
- decoded_data: 解码后的数据
- mapping_table: 映射表
- processing_status: 处理状态

请根据用户需求和当前状态，自主决定下一步操作。
"""
