# 数据映射Agent - 全面改造计划

> 文档版本：v3.0  
> 创建时间：2026-04-22  
> 更新时间：2026-04-22  
> 目标：基于Agno原生能力，构建智能、自主、具备记忆的Agent  
> 分支：`feature/intelligent-agent`

---

## 一、项目现状与目标

### 1.1 当前问题

| 问题 | 描述 | 影响 |
|------|------|------|
| **缺乏自主思考** | Agent只是按固定流程执行命令 | 用户需要一步步引导 |
| **功能独立** | 各功能模块独立，无法自动组合 | 无法一次性完成复杂任务 |
| **无记忆能力** | 无法记忆处理历史和偏好 | 重复工作，效率低 |
| **Human-in-loop实现复杂** | 需要手动实现确认机制 | 开发成本高 |

### 1.2 改造目标

1. **自主思考**：Agent能理解用户意图，自动规划任务
2. **功能组合**：根据需求自动组合多个功能模块
3. **记忆系统**：持久化会话状态，记忆处理历史
4. **智能交互**：在关键节点自动暂停，等待用户确认
5. **技能系统**：使用Agno的Skills组织工具集
6. **多模型策略**：简单任务用简单模型，复杂任务用推理模型
7. **用户配置**：支持自定义API Key和模型选择（优化项）

---

## 二、测试策略

### 2.1 测试分工

| 测试类型 | 负责方 | 说明 |
|---------|--------|------|
| **代码语法检查** | 我 | 确保代码无语法错误 |
| **导入依赖检查** | 我 | 确保所有依赖正确导入 |
| **数据结构验证** | 我 | 确保数据处理逻辑正确 |
| **LLM API调用测试** | 你 | 需要真实API Key |
| **端到端交互测试** | 你 | 需要你体验完整流程 |
| **异常场景测试** | 我们配合 | 我写测试用例，你执行验证 |

### 2.2 测试方式

我会进行**基础功能测试**（不涉及LLM调用），涉及LLM的部分需要你来测试和体验。

---

## 三、MVP定义

### 3.1 MVP = Minimum Viable Product（最小可行产品）

MVP阶段聚焦核心功能，快速验证可行性。

### 3.2 MVP功能清单

| MVP功能 | 优先级 | 说明 |
|---------|--------|------|
| **Agent主入口** | ⭐⭐⭐⭐⭐ | 整合所有Agno原生能力 |
| **会话状态管理** | ⭐⭐⭐⭐⭐ | 保存中间结果 |
| **自动解码** | ⭐⭐⭐⭐⭐ | Base64自动解码 |
| **字段映射** | ⭐⭐⭐⭐⭐ | 生成映射表 |
| **HITL确认** | ⭐⭐⭐⭐ | 关键节点暂停 |
| **历史记录** | ⭐⭐⭐ | 多轮对话续接 |
| **多模型策略** | ⭐⭐⭐⭐ | 采纳用户建议，简单任务用小模型 |

### 3.3 MVP不包括（后续迭代）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 记忆系统（MemoryManager） | ⭐⭐⭐ | 跨会话记忆 |
| 技能系统（Skills） | ⭐⭐⭐ | Skills组织 |
| 用户自定义API Key | ⭐⭐ | 自定义配置面板 |

---

## 四、多模型策略 ⭐

### 4.1 策略说明

采纳用户建议：不同任务用不同模型，节省Token成本。

| 任务类型 | 推荐模型 | 成本 | 用途 |
|---------|---------|------|------|
| **简单任务** | DeepSeek-V3 | 💰 低 | Base64解码、字段提取 |
| **复杂推理** | DeepSeek-R1 | 💰💰 中 | 字段映射、意图理解 |
| **生成任务** | DeepSeek-V3.2 | 💰💰 中 | 生成映射表、总结 |
| **轻量对话** | Qwen/QWQ | 💰 低 | 历史续接、简单问答 |

### 4.2 Agno多模型配置

```python
# 不同Agent用不同模型
from agno.agent import Agent
from agno.models.siliconflow import Siliconflow

# 简单任务Agent
simple_agent = Agent(
    model=Siliconflow(id="deepseek-ai/DeepSeek-V3"),
    tools=[base64_decode_tool]
)

# 复杂推理Agent
complex_agent = Agent(
    model=Siliconflow(id="deepseek-ai/DeepSeek-R1"),
    tools=[field_mapping_tool, threat_type_tool]
)

# 主控Agent（意图理解）
main_agent = Agent(
    model=Siliconflow(id="deepseek-ai/DeepSeek-V3.2"),
    tools=[simple_agent, complex_agent]
)
```

### 4.3 任务路由逻辑

```python
def route_task(task: str, session_state: dict) -> str:
    """根据任务类型路由到不同Agent"""
    
    if "解码" in task or "Base64" in task:
        return "simple_agent"  # 用简单模型
    
    elif "映射" in task or "标准化" in task:
        return "complex_agent"  # 用推理模型
    
    elif "总结" in task or "导出" in task:
        return "simple_agent"  # 用简单模型
    
    else:
        return "main_agent"  # 用主模型
```

---

## 五、API提供商切换

### 5.1 切换便捷性

Agno原生支持多提供商，切换非常方便：

```python
# 只需改配置，代码逻辑不变

# 方案1: SiliconFlow
from agno.models.siliconflow import Siliconflow
model = Siliconflow(id="deepseek-ai/DeepSeek-V3.2", api_key="xxx")

# 方案2: OpenAI
from agno.models.openai import OpenAIChat
model = OpenAIChat(id="gpt-4o", api_key="xxx")

# 方案3: Anthropic
from agno.models.anthropic import Claude
model = Claude(id="claude-sonnet-4-6", api_key="xxx")

# 方案4: 本地模型
from agno.models.ollama import Ollama
model = Ollama(id="llama3")
```

### 5.2 抽象层设计

为后续切换方便，可以抽象模型配置：

```python
# agent/config/model_config.py
class ModelConfig:
    """模型配置抽象"""
    
    PROVIDERS = {
        "siliconflow": {
            "class": Siliconflow,
            "default_model": "deepseek-ai/DeepSeek-V3.2"
        },
        "openai": {
            "class": OpenAIChat,
            "default_model": "gpt-4o"
        },
        "anthropic": {
            "class": Claude,
            "default_model": "claude-sonnet-4-6"
        }
    }
    
    @staticmethod
    def get_model(provider: str, model_id: str, api_key: str):
        """获取模型实例"""
        config = ModelConfig.PROVIDERS.get(provider)
        if not config:
            raise ValueError(f"不支持的提供商: {provider}")
        
        return config["class"](id=model_id, api_key=api_key)
```

---

## 六、用户自定义API Key（优化项） ⭐

### 6.1 功能设计

MVP后可以加入用户自定义配置功能：

```
┌─────────────────────────────────────┐
│        设置面板                      │
│  ┌───────────────────────────────┐  │
│  │ LLM提供商: [SiliconFlow ▼]   │  │
│  │ API Key: [*************]     │  │
│  │ 模型选择: [DeepSeek-V3.2 ▼]  │  │
│  │                               │  │
│  │ [保存配置]                    │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

### 6.2 实现方案

```python
# agent/config/user_config.py
import streamlit as st

def render_config_panel():
    """渲染配置面板"""
    
    with st.sidebar:
        st.header("⚙️ API配置")
        
        provider = st.selectbox(
            "选择提供商",
            ["siliconflow", "openai", "anthropic"]
        )
        
        api_key = st.text_input(
            "API Key",
            type="password",
            value=st.session_state.get("api_key", "")
        )
        
        model_id = st.selectbox(
            "选择模型",
            get_available_models(provider)
        )
        
        if st.button("💾 保存配置"):
            st.session_state.api_key = api_key
            st.session_state.model_id = model_id
            st.session_state.provider = provider
            st.success("配置已保存！")
```

### 6.3 优先级

| 阶段 | 功能 | 优先级 |
|------|------|--------|
| MVP | 使用环境变量配置 | ⭐⭐⭐⭐⭐ |
| 优化 | 用户自定义API Key | ⭐⭐ |

---

## 七、Agno原生能力分析

### 7.1 核心能力矩阵

| 能力模块 | Agno原生功能 | 用途 | 优先级 |
|----------|--------------|------|--------|
| **会话管理** | `SqliteDb` + `session_state` | 持久化会话，保存中间状态 | ⭐⭐⭐⭐⭐ |
| **历史记录** | `add_history_to_context` + `num_history_runs` | 上下文续接，多轮对话 | ⭐⭐⭐⭐⭐ |
| **记忆系统** | `MemoryManager` + `enable_agentic_memory` | 跨会话记忆，学习用户偏好 | ⭐⭐⭐⭐ |
| **技能系统** | `Skills` + `LocalSkills` | 组织和管理工具集 | ⭐⭐⭐⭐⭐ |
| **Human-in-loop** | `@tool(requires_confirmation=True)` | 关键操作需用户确认 | ⭐⭐⭐⭐⭐ |
| **状态管理** | `session_state` | 单会话内状态共享 | ⭐⭐⭐⭐⭐ |
| **结构化输出** | `output_schema` | 规范化Agent响应格式 | ⭐⭐⭐ |
| **知识库** | `Knowledge` + `vector_db` | RAG增强问答 | ⭐⭐ |

### 7.2 Agno Cookbook参考

```
agno-main/cookbook/
├── 02_agents/
│   ├── 05_state_and_session/     # 会话和状态管理 ⭐
│   ├── 06_memory_and_learning/   # 记忆系统 ⭐
│   ├── 10_human_in_the_loop/    # HITL机制 ⭐
│   ├── 16_skills/              # 技能系统 ⭐
│   └── 03_context_management/   # 上下文管理
├── 03_teams/                   # 多Agent协作
├── 04_workflows/               # 工作流模式
├── 07_knowledge/               # 知识库RAG
└── 11_memory/                  # 内存管理
```

---

## 八、改造架构设计

### 8.1 整体架构

```
┌────────────────────────────────────────────────────────────────────┐
│                         用户交互层                                  │
│                    (Streamlit Web界面)                              │
│         ┌──────────────────────────────────────────────┐           │
│         │           设置面板（优化项）                   │           │
│         │  • LLM提供商选择                              │           │
│         │  • API Key配置                               │           │
│         │  • 模型选择                                   │           │
│         └──────────────────────────────────────────────┘           │
└────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                      Agno Agent（核心）                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    会话管理层                                  │  │
│  │  • SqliteDb（持久化）                                        │  │
│  │  • session_state（状态共享）                                 │  │
│  │  • add_history_to_context（历史续接）                         │  │
│  │  • MemoryManager（跨会话记忆）                                │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    多模型策略层 ⭐                              │  │
│  │  • SimpleAgent（简单任务）                                    │  │
│  │  • ComplexAgent（复杂推理）                                   │  │
│  │  • MainAgent（主控协调）                                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    技能系统层                                  │  │
│  │  • Skills（技能集合）                                        │  │
│  │  • Base64Skill                                              │  │
│  │  • FieldMappingSkill                                         │  │
│  │  • ThreatTypeSkill                                           │  │
│  │  • EnumSkill                                                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    推理引擎层                                  │  │
│  │  • 理解用户意图                                               │  │
│  │  • 规划任务步骤                                               │  │
│  │  • 决策工具调用                                               │  │
│  │  • 评估执行结果                                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                      Tools层（保持不变）                             │
│  • base64_tool.py                                                │
│  • standard_mapper.py                                            │
│  • threat_type_tool.py                                            │
│  • enum_field_tool.py                                            │
└────────────────────────────────────────────────────────────────────┘
```

### 8.2 新目录结构

```
agent/
├── __init__.py
│
├── core/                          # 【新增】核心Agent
│   ├── __init__.py
│   ├── agent.py                  # Agent主入口
│   ├── prompts.py                 # System Prompt
│   └── model_config.py           # 【新增】模型配置
│
├── skills/                        # 【新增】技能系统
│   ├── __init__.py
│   ├── base64_skill.py           # Base64技能
│   ├── field_mapping_skill.py    # 字段映射技能
│   ├── threat_type_skill.py      # 威胁类型技能
│   └── enum_skill.py             # 枚举处理技能
│
├── memory/                        # 【新增】记忆系统
│   ├── __init__.py
│   ├── session_manager.py        # 会话管理器
│   └── memory_manager.py         # 记忆管理器
│
├── tools/                         # 【保留】底层工具
│   ├── __init__.py
│   ├── base64_tool.py
│   ├── standard_mapper.py
│   ├── threat_type_tool.py
│   ├── enum_field_tool.py
│   └── file_tool.py
│
├── prompts/                       # 【改造】提示词
│   ├── __init__.py
│   ├── system_prompt.py          # 系统提示词
│   └── skill_prompts.py          # 技能提示词
│
└── data/                          # 【保留】数据文件
    ├── 标准字段.txt
    └── .gitkeep
```

---

## 九、详细实施计划

### MVP阶段（约3天）

| 阶段 | 功能 | 负责 |
|------|------|------|
| **MVP-1** | Agent主入口 + 会话管理 | 我 |
| **MVP-2** | 自动解码 + 字段映射 | 我 |
| **MVP-3** | HITL确认机制 | 我 |
| **MVP-4** | 基础测试（语法、数据结构） | 我 |
| **MVP-5** | Streamlit集成 | 我 |
| **MVP-6** | 端到端测试（需要API Key） | 我们配合 |

### 优化阶段（后续迭代）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| **多模型策略** | ⭐⭐⭐⭐ | 采纳用户建议，简单任务用小模型 |
| **记忆系统** | ⭐⭐⭐ | 跨会话记忆 |
| **技能系统** | ⭐⭐⭐ | Skills组织 |
| **用户API Key** | ⭐⭐ | 自定义配置面板 |

---

### Phase 1: 会话与状态管理系统（0.5天）

#### Step 1.1: 会话管理器

```python
# agent/memory/session_manager.py
from agno.db.sqlite import SqliteDb
from typing import Optional

class SessionManager:
    """会话管理器 - 利用Agno原生SqliteDb"""
    
    def __init__(self, db_path: str = "tmp/agents.db"):
        self.db = SqliteDb(db_file=db_path)
    
    def get_agent(self, user_id: str, session_id: Optional[str] = None):
        """创建/获取Agent实例"""
        return Agent(
            db=self.db,
            user_id=user_id,
            session_id=session_id,
            # 启用历史记录
            add_history_to_context=True,
            num_history_runs=5,
            # 初始化会话状态
            session_state={
                "uploaded_file": None,
                "decoded_data": None,
                "mapping_table": None,
                "processing_status": "idle"
            },
        )
```

**Agno原生能力**：
- `SqliteDb`: 自动持久化会话
- `add_history_to_context`: 自动续接历史
- `num_history_runs`: 控制历史长度

#### Step 1.2: 状态共享机制

```python
# 在Tool中使用session_state
from agno.run import RunContext

def decode_base64_tool(run_context: RunContext, b64_text: str) -> dict:
    """解码Base64并保存到session_state"""
    
    # 解码
    decoded = base64_decode_and_extract(b64_text)
    
    # 保存到session_state
    if run_context.session_state is None:
        run_context.session_state = {}
    
    run_context.session_state["decoded_data"] = decoded
    run_context.session_state["uploaded_file"] = b64_text
    
    return decoded
```

**Agno原生能力**：
- `RunContext.session_state`: 工具间共享状态

---

### Phase 2: 多模型策略（0.5天） ⭐

#### Step 2.1: 模型配置

```python
# agent/core/model_config.py
from agno.models.siliconflow import Siliconflow
from typing import Optional

class ModelConfig:
    """多模型配置"""
    
    # 简单任务模型（低成本）
    SIMPLE_MODEL = "deepseek-ai/DeepSeek-V3"
    
    # 复杂推理模型（高成本）
    COMPLEX_MODEL = "deepseek-ai/DeepSeek-R1"
    
    # 主控模型（平衡）
    MAIN_MODEL = "deepseek-ai/DeepSeek-V3.2"
    
    @staticmethod
    def get_api_key() -> str:
        """从环境变量获取API Key"""
        import os
        return os.getenv("SILICONFLOW_API_KEY", "")
    
    @staticmethod
    def get_simple_model():
        """获取简单任务模型"""
        return Siliconflow(
            id=ModelConfig.SIMPLE_MODEL,
            api_key=ModelConfig.get_api_key()
        )
    
    @staticmethod
    def get_complex_model():
        """获取复杂推理模型"""
        return Siliconflow(
            id=ModelConfig.COMPLEX_MODEL,
            api_key=ModelConfig.get_api_key()
        )
    
    @staticmethod
    def get_main_model():
        """获取主控模型"""
        return Siliconflow(
            id=ModelConfig.MAIN_MODEL,
            api_key=ModelConfig.get_api_key()
        )
```

#### Step 2.2: 多Agent定义

```python
# agent/core/agent.py
from agno.agent import Agent

def create_simple_agent():
    """简单任务Agent（Base64解码等）"""
    return Agent(
        model=ModelConfig.get_simple_model(),
        name="SimpleAgent",
        tools=[base64_decode_tool],
        description="处理简单的数据转换任务"
    )

def create_complex_agent():
    """复杂推理Agent（字段映射等）"""
    return Agent(
        model=ModelConfig.get_complex_model(),
        name="ComplexAgent",
        tools=[field_mapping_tool, threat_type_tool],
        description="处理需要推理的复杂任务"
    )

def create_main_agent():
    """主控Agent（意图理解、协调）"""
    return Agent(
        model=ModelConfig.get_main_model(),
        name="MainAgent",
        tools=[create_simple_agent, create_complex_agent],
        description="理解用户意图，协调任务执行"
    )
```

---

### Phase 3: Human-in-the-Loop（0.5天）

#### Step 3.1: 确认工具定义

```python
# agent/tools/confirmation_tool.py
from agno.tools import tool

@tool(requires_confirmation=True)
def confirm_mapping_table(
    mapping_table: list,
    step_name: str = "字段映射",
    confirmation_message: str = "请确认字段映射表"
) -> dict:
    """
    展示映射表并请求用户确认
    
    此工具会自动暂停执行，等待用户确认后才继续。
    
    Args:
        mapping_table: 映射表数据
        step_name: 步骤名称
        confirmation_message: 确认提示
    
    Returns:
        确认结果
    """
    return {
        "status": "waiting_confirmation",
        "step_name": step_name,
        "data": mapping_table,
        "message": confirmation_message
    }
```

**Agno原生能力**：
- `@tool(requires_confirmation=True)`: 自动暂停执行
- `run_response.active_requirements`: 检查待确认项
- `requirement.confirm()`: 确认执行

#### Step 3.2: 前端确认处理

```python
# web/app.py
def handle_confirmation(response, agent):
    """处理确认请求"""
    
    if not hasattr(response, 'active_requirements'):
        return response
    
    for requirement in response.active_requirements:
        if requirement.needs_confirmation:
            st.warning(f"⚠️ {requirement.confirmation_message}")
            
            tool_args = requirement.tool_execution.tool_args
            if 'mapping_table' in tool_args:
                st.table(tool_args['mapping_table'])
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ 确认"):
                    requirement.confirm()
                    response = agent.continue_run(
                        run_id=response.run_id,
                        requirements=response.requirements
                    )
            with col2:
                if st.button("✏️ 修改"):
                    st.session_state.editing = True
    
    return response
```

---

### Phase 4: 自主推理引擎（0.5天）

#### Step 4.1: System Prompt重构

```python
# agent/core/prompts.py
SYSTEM_PROMPT = """
# 数据映射智能助手

## 核心能力

你是一个**自主思考**的智能助手，具备以下能力：

1. **意图理解**：理解用户的自然语言需求
2. **任务规划**：决定需要哪些步骤
3. **技能调用**：自动选择合适的技能执行
4. **状态管理**：利用session_state管理中间结果
5. **记忆利用**：从记忆中学习用户偏好
6. **人工协作**：在关键节点请求用户确认

## 工作模式

### 自动执行
- Base64解码（自动）
- 字段提取（自动）
- 映射表生成（自动）

### 需确认节点
- 字段映射表展示后（等待确认）
- 威胁类型映射后（等待确认）
- 最终输出前（等待确认）

## 示例交互

用户: "处理这个Base64，完成字段映射"

你:
1. 识别需要base64_decode技能 → 自动解码
2. 识别需要field_mapping技能 → 生成映射表
3. 调用confirm_mapping_table → 等待确认
4. 用户确认后 → 执行映射
5. 返回最终结果
"""
```

---

### Phase 5: 前端集成（1天）

```python
# web/app.py
import streamlit as st
from agent.core.agent import create_main_agent

def main():
    st.title("数据映射智能助手")
    
    # 初始化Agent
    if "agent" not in st.session_state:
        st.session_state.agent = create_main_agent()
    
    agent = st.session_state.agent
    
    # 文件上传
    uploaded_file = st.file_uploader("上传Base64文件")
    
    if uploaded_file:
        b64_content = uploaded_file.read().decode('utf-8')
        
        with st.spinner("智能处理中..."):
            response = agent.run(f"处理这个Base64: {b64_content}")
        
        # 处理确认
        if hasattr(response, 'active_requirements'):
            response = handle_confirmation(response, agent)
        
        st.markdown(response.content)
```

---

## 十、实施清单

### MVP技术任务

| 阶段 | 任务 | 优先级 | 状态 |
|------|------|--------|------|
| **MVP-1** | 会话管理器 | ⭐⭐⭐⭐⭐ | |
| │ 1.1 | SqliteDb配置 | | |
| │ 1.2 | 状态共享机制 | | |
| **MVP-2** | 多模型策略 ⭐ | ⭐⭐⭐⭐ | |
| │ 2.1 | 模型配置抽象 | | |
| │ 2.2 | 多Agent定义 | | |
| │ 2.3 | 任务路由逻辑 | | |
| **MVP-3** | Human-in-the-Loop | ⭐⭐⭐⭐⭐ | |
| │ 3.1 | 确认工具定义 | | |
| │ 3.2 | 前端确认处理 | | |
| **MVP-4** | 自主推理引擎 | ⭐⭐⭐⭐ | |
| │ 4.1 | System Prompt重构 | | |
| **MVP-5** | 前端集成 | ⭐⭐⭐⭐ | |
| │ 5.1 | Streamlit集成 | | |
| **MVP-6** | 端到端测试 | ⭐⭐⭐⭐⭐ | |

### 优化任务

| 任务 | 优先级 | 说明 |
|------|--------|------|
| 记忆系统 | ⭐⭐⭐ | 跨会话记忆 |
| 技能系统 | ⭐⭐⭐ | Skills组织 |
| 用户API Key | ⭐⭐ | 自定义配置面板 |

---

## 十一、预期效果

### 11.1 改造前

```
用户: "处理这个Base64"
Agent: "请提供Base64数据"
用户: [上传文件]
Agent: "已解码，请确认字段映射"
用户: "确认"
Agent: "请告诉我如何映射威胁类型"
用户: "标准化"
Agent: [执行威胁类型标准化]
...（用户需要一步步引导）
```

### 11.2 改造后

```
用户: "处理这个Base64，完成字段映射和威胁类型标准化"
Agent: "好的，我来帮您完成这个任务。
       
       执行计划：
       1. 解码Base64数据（使用简单模型）
       2. 生成字段映射表（使用推理模型）
       3. 标准化威胁类型
       4. 生成最终输出
       
       开始执行..."
       
       [自动执行完整流程]
       
Agent: "字段映射表已生成，请确认：
       
       | 原始字段 | 标准字段 |
       |----------|----------|
       | srcip    | 源地址   |
       | dstip    | 目的地址 |
       ...
       
       [等待确认]"
```

### 11.3 记忆功能（优化项）

```
用户1: "处理这个数据"
Agent: [完成处理，记忆映射偏好]

用户1: "处理另一个数据"
Agent: [检索记忆]
       "我注意到您之前偏好xxx映射规则，是否沿用？"
```

---

## 十二、技术栈总结

| 模块 | Agno原生能力 | 自定义程度 |
|------|-------------|-----------|
| 会话管理 | `SqliteDb` + `session_state` | 低 |
| 历史记录 | `add_history_to_context` | 低 |
| 多模型策略 | 多Agent + 不同模型配置 ⭐ | 中 |
| Human-in-loop | `@tool(requires_confirmation=True)` | 低 |
| 工具系统 | `@tool` | 低 |
| 推理引擎 | System Prompt | 中 |
| 记忆系统 | `MemoryManager`（优化项） | 中 |
| 用户API Key | 前端配置（优化项） | 中 |

---

## 十三、风险与注意事项

### 13.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 上下文长度限制 | 654行标准字段表可能超限 | 分批传入，或使用摘要 |
| LLM调用成本 | 多步骤组合导致多次调用 | 多模型策略优化 |
| 会话持久化 | 大量会话占用磁盘 | 定期清理历史 |

### 13.2 开发注意事项

1. **Agent复用**：不要在循环中创建Agent
2. **session_state初始化**：首次使用时初始化
3. **异常处理**：Tool执行失败要清理状态
4. **前端适配**：确认交互需要前端支持
5. **API Key安全**：用户配置要加密存储

---

## 十四、后续扩展方向

1. **多Agent协作**：使用Team模式
2. **知识库RAG**：使用Knowledge增强问答
3. **流式输出**：使用streaming实时展示进度
4. **监控分析**：集成AgentOS监控面板
5. **用户自定义API Key**：配置面板

---

*文档由AI Agent生成，如有问题请联系维护者。*
