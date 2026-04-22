# 数据映射解析工具 — Agno Agent 改造计划

> 文档版本：v1.1
> 创建时间：2026-04-20
> 更新时间：2026-04-20
> 目标：将现有 tkinter GUI 桌面工具改造为基于 Agno + Streamlit 的 Web Agent

---

## 一、项目概述

### 1.1 现有系统

- **名称**：数据映射解析工具
- **现状**：基于 Python tkinter 的桌面应用，包含 5 大功能模块
- **核心用途**：处理安全设备的 Base64 编码 JSON 解析规则，进行字段映射和编码转换

### 1.2 改造目标

将现有桌面工具改造为 **Web 端对话式智能体**，用户通过自然语言 + 文件上传与 Agent 交互，实现：
1. Base64 自动解码 → 字段提取
2. LLM 智能分析 → 标准字段映射表生成
3. Human-in-the-Loop → 表格确认 / 对话修改
4. 自动字段填充 → Base64 加密输出

### 1.3 关键技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| Agent 框架 | Agno | 作为 Agent 核心框架 |
| LLM | DeepSeek-V3.2 | 通过 SiliconFlow API 调用 |
| 前端框架 | Streamlit | 快速构建数据科学 Web 应用 |
| 前端 UI | Streamlit 原生组件 + 自定义 CSS | 包含可编辑表格、文件上传、聊天界面 |
| 存储 | 本地文件系统 / SQLite | 轻量级会话状态管理 |

---

## 二、边界问题确认

| # | 问题 | 答案 |
|---|------|------|
| 1 | LLM 模型 | `deepseek-ai/DeepSeek-V3.2`（SiliconFlow） |
| 2 | 标准字段表 | **全量传入** LLM（`auto/phase2/data/标准字段.txt`，654 行） |
| 3 | Excel 对应关系 Sheet | 用于生成映射后的 Excel 填充逻辑（复用 `src/handlers/standard_field_mapping_handler.py`） |
| 4 | 前端框架 | Streamlit | 
| 5 | Human-in-the-Loop 方式 | **方案 A**：表格确认 + LLM 对话修改 |
| 6 | 最终输出 | Base64 加密数据（可下载） |

---

## 三、目标架构

### 3.1 整体流程

```
┌──────────────────────────────────────────────────────────────┐
│                      用户 (Web Browser)                       │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Streamlit Backend (Python Server)                  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              HTTP Server                                 │ │
│  │  GET  /           → 主页面 (HTML渲染)                    │ │
│  │  POST /upload     → 文件上传 (st.file_uploader)         │ │
│  │  POST /chat       → Agent 对话 (session_state)          │ │
│  │  GET  /download   → 结果下载 (st.download_button)        │ │
│  └─────────────────────────────────────────────────────────┘ │
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    Agno Agent                                 │
│  Model: DeepSeek-V3.2 (SiliconFlow)                          │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Tools:                                                  │ │
│  │  • base64_tool        → Base64 解码 + 字段提取           │ │
│  │  • standard_mapper    → 标准字段映射 + Excel 填充        │ │
│  │  • base64_encoder     → Base64 编码输出                  │ │
│  │  • file_tool          → 文件读写                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ System Prompts:                                         │ │
│  │  • field_weak.md       → 弱匹配标准字段映射               │ │
│  │  • field_strong.md     → 强匹配标准字段映射               │ │
│  │  • threat_type.md      → 威胁类型标准化                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    参考数据文件                                │
│  • 标准字段.txt (654行)  → 全量传入 LLM                      │
│  • 对象.xlsx (对应关系Sheet) → 用于 Excel 填充逻辑            │
│  • threat_type_config.json → 威胁类型标准化配置               │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Human-in-the-Loop 交互流程

```
Step 1: 用户上传 Base64 文件
        ↓
Step 2: Agent 调用 base64_tool → 解码 + 提取字段
        ↓
Step 3: Agent 调用 LLM → 生成标准字段映射表 (Markdown)
        ↓
Step 4: 前端渲染可编辑表格
        ↓
Step 5: [HUMAN] 用户确认/修改映射表
        │
        ├─── 确认 ──→ 提交给 Agent
        │
        └─── 修改 ──→ 通过对话告诉 Agent 修改内容
                      Agent 更新表格 → 重新渲染
        ↓
Step 6: Agent 调用 standard_mapper → 执行映射逻辑
        ↓
Step 7: Agent 调用 base64_encoder → Base64 编码
        ↓
Step 8: 输出最终 Base64 数据（提供下载链接）
```

---

## 四、项目目录结构

```
toolswithagent/
│
├── agent/                          # 【新增】Agno Agent 核心
│   ├── __init__.py
│   │
│   ├── tools/                       # Agno Tools
│   │   ├── __init__.py
│   │   ├── base64_tool.py          # Tool: Base64 解码 + 字段提取
│   │   │                              复用 auto/phase1/index.py 逻辑
│   │   ├── standard_mapper.py       # Tool: 标准字段映射 + Excel 填充
│   │   │                              复用 src/handlers/standard_field_mapping_handler.py
│   │   ├── base64_encoder.py        # Tool: Base64 编码输出
│   │   ├── file_tool.py             # Tool: 文件读写
│   │   └── excel_tool.py            # Tool: Excel 操作
│   │
│   ├── prompts/                     # System Prompts
│   │   ├── __init__.py
│   │   ├── field_weak.md            # 弱匹配标准字段映射（复制自 auto/phase2/标准字段.md）
│   │   ├── field_strong.md           # 强匹配标准字段映射（复制自 auto/phase2/提示词-强匹配.md）
│   │   └── threat_type.md           # 威胁类型标准化（复制自 auto/phase2/威胁类型.md）
│   │
│   ├── data/                        # 参考数据
│   │   ├── 标准字段.txt             # 654行标准字段表（复制自 auto/phase2/data/）
│   │   └── .gitkeep
│   │
│   ├── models/                      # 数据模型
│   │   ├── __init__.py
│   │   ├── field_mapping.py         # 字段映射数据模型
│   │   └── processing_result.py     # 处理结果数据模型
│   │
│   └── agent.py                     # Agent 定义
│
├── src/                            # 【改造】现有 tkinter 代码
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── standard_field_mapping_handler.py  # 剥离 GUI，保留纯业务逻辑
│   │
│   └── ...                          # 其他 handler（暂不改动）
│
├── web/                            # 【新增】Streamlit Web 前端
│   ├── app.py                      # Streamlit 应用入口
│   ├── requirements.txt             # Python 依赖
│   │
│   ├── pages/                      # Streamlit 多页面
│   │   ├── 1_主页.py               # 主页 - 文件上传和 Agent 对话
│   │   └── 2_历史记录.py           # 历史处理记录
│   │
│   └── components/                  # Streamlit 组件
│       ├── __init__.py
│       ├── chat_container.py        # 聊天消息容器
│       ├── file_uploader.py         # 文件上传组件
│       ├── field_table.py           # 可编辑字段映射表格
│       └── download_button.py       # 下载按钮组件
├── config/                         # 【复用】现有配置
│   ├── 对象.xlsx                   # 对应关系 Sheet
│   ├── threat_type_config.json     # 威胁类型配置
│   └── ...
│
├── auto/                           # 【复用】现有 auto 框架
│   ├── phase1/                    # Base64 解码逻辑
│   ├── phase2/                    # 提示词和标准字段表
│   ├── phase3/                    # 字段提取逻辑
│   └── allinone/                  # 流水线框架
│
├── plan/                          # 【本计划文档】
│   └── AGENT改造计划.md           # 本文档
│
├── main.py                        # 【保留】tkinter 主程序（可选，演示用）
├── requirements.txt               # Python 依赖
└── README.md                     # 项目说明
```

---

## 五、详细实施计划

### Phase 1：Agent 核心 — Agno Tools 开发

#### Step 1.1: base64_tool.py — Base64 解码 + 字段提取

**目标**：封装 auto/phase1/index.py 的核心逻辑为 Agno Tool

**输入**：
- Base64 编码的文本内容（字符串）

**输出**：
```python
{
    "decoded_json": {...},           # 解码后的 JSON 对象
    "decoded_text": "...",          # 解码后的文本
    "fields": [...],                 # 提取的 normalize indexes 数组
    "original_log": {...},           # original_log 对应的 result
    "status": "success" | "error",
    "error_message": "..."           # 如果失败
}
```

**核心逻辑**：
```python
from auto.phase1.index import decode_base64_text, extract_normalize_indexes, _extract_original_log_result

@tool(name="base64_decode_and_extract", description="解码 Base64 文本并提取字段信息")
def base64_decode_and_extract(b64_text: str) -> dict:
    """将 Base64 编码的文本解码为 JSON，并提取 normalize indexes 中的字段列表"""
    # 清理空白字符
    cleaned = "".join(b64_text.split())
    
    # 补齐 padding
    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)
    
    # 解码
    decoded_bytes = base64.b64decode(cleaned)
    decoded_text = decoded_bytes.decode("utf-8", errors="replace")
    
    # 提取字段
    fields = extract_normalize_indexes(decoded_text)
    original_log = _extract_original_log_result(decoded_text)
    
    return {
        "decoded_json": json.loads(decoded_text),
        "decoded_text": decoded_text,
        "fields": fields,
        "original_log": original_log,
        "status": "success"
    }
```

---

#### Step 1.2: standard_mapper.py — 标准字段映射 + Excel 填充

**目标**：封装 src/handlers/standard_field_mapping_handler.py 的核心逻辑为 Agno Tool

**输入**：
- 解码后的 JSON 对象
- 字段映射表（Markdown 表格或 dict list）
- Excel 模板路径（可选）

**输出**：
```python
{
    "processed_json": {...},         # 映射后的 JSON 对象
    "excel_file": "...",             # 生成的 Excel 文件路径（可选）
    "entities_added": [...],         # 添加到 simEntities 的实体列表
    "status": "success" | "partial" | "error"
}
```

**核心逻辑**：
1. 读取 `config/对象.xlsx` 的"对应关系" Sheet
2. 根据映射表建立字段与对象的映射
3. 自动将新实体添加到 simEntities 数组
4. 输出修改后的 JSON

---

#### Step 1.3: base64_encoder.py — Base64 编码输出

**目标**：将处理后的 JSON 编码为 Base64

**输入**：
- JSON 对象（dict 或 str）

**输出**：
```python
{
    "base64_encoded": "...",         # Base64 编码字符串
    "decoded_preview": "...",        # 前 200 字符预览
    "status": "success" | "error"
}
```

---

#### Step 1.4: file_tool.py — 文件读写工具

**目标**：提供通用的文件读写能力

**Tool 函数**：
```python
@tool
def read_file(file_path: str) -> str:
    """读取文件内容"""
    
@tool
def write_file(file_path: str, content: str) -> str:
    """写入文件内容"""
    
@tool
def list_files(directory: str) -> list[str]:
    """列出目录下的文件"""
```

---

### Phase 2：Agent 核心 — Agno Agent 定义

#### Step 2.1: agent.py — Agent 定义

**目标**：创建 Agno Agent，接入 SiliconFlow 的 DeepSeek-V3.2

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agent.tools import (
    base64_decode_and_extract,
    standard_field_mapping,
    base64_encode,
    read_file,
    write_file
)
from agent.prompts import load_field_weak_prompt, load_field_strong_prompt

# 加载标准字段表（654行全量）
STANDARD_FIELDS = load_standard_fields_txt("agent/data/标准字段.txt")

def create_agent(session_id: str = None):
    """创建 Agent 实例"""
    
    system_prompt = f"""
    {load_field_weak_prompt()}
    
    ## 标准字段表（必须严格使用以下中文名称）
    {STANDARD_FIELDS}
    
    ## 你的任务
    1. 接收用户上传的 Base64 编码数据
    2. 调用 base64_decode_and_extract 工具解码并提取字段
    3. 根据标准字段表生成字段映射表（Markdown 表格格式）
    4. 等待用户确认或修改映射表
    5. 用户确认后，调用 standard_field_mapping 执行映射
    6. 调用 base64_encode 输出最终 Base64 数据
    """
    
    return Agent(
        model=OpenAIChat(
            id="deepseek-ai/DeepSeek-V3.2",
            base_url="https://api.siliconflow.cn/v1",
            api_key=os.getenv("SILICONFLOW_API_KEY"),
        ),
        tools=[
            base64_decode_and_extract,
            standard_field_mapping,
            base64_encode,
            read_file,
            write_file
        ],
        system_prompt=system_prompt,
        description="安全设备配置规则字段映射智能助手",
        user_id=session_id or "anonymous",
        markdown=True,
    )
```

---

### Phase 3：前端 — Streamlit Web 应用

#### Step 3.1: Streamlit 项目初始化

```bash
# 安装 Streamlit
pip install streamlit

# 运行应用
cd web
streamlit run app.py
```

#### Step 3.2: 核心页面设计

| 页面 | 组件 | 说明 |
|------|------|------|
| `/` (主页) | st.file_uploader | 上传 Base64 文件 |
| `/` (主页) | st.session_state | 存储会话上下文 |
| `/` (主页) | st.chat_message | 展示对话消息 |
| `/` (主页) | st.data_editor | 可编辑字段映射表格 |
| `/` (主页) | st.download_button | 下载最终 Base64 文件 |
| `/history` | st.dataframe | 历史处理记录 |

#### Step 3.3: 前端 UI 设计

**页面结构**（Streamlit 原生组件）：
```
┌─────────────────────────────────────────────────────────────┐
│  🔐  数据映射解析工具                      [🏠 主页] [📜 历史] │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  📁 上传 Base64 文件                                    │ │
│  │  [拖拽或点击上传 .txt/.b64 文件]                       │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 🤖 Assistant                                            │  │
│  │ 请上传您的 Base64 编码文件，我会帮您解码并生成字段映射表 │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 👤 User                                                │ │
│  │ [上传了 config.b64]                                    │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 🤖 Assistant                                            │ │
│  │ 📋 标准字段映射表：                                   │  │
│  │                                                        │  │
│  │ ┌──────────────────────────────────────────────────┐  │ │
│  │ │ st.data_editor (可编辑表格)                       │  │ │
│  │ │ ┌────────────────┬──────────────┬──────────────┐│  │ │
│  │ │ │原始字段名       │系统属性名称 ▼│匹配状态      ││  │ │
│  │ │ ├────────────────┼──────────────┼──────────────┤│  │ │
│  │ │ │content.srcip   │源地址        │✓ 匹配成功    ││  │ │
│  │ │ │content.dstip   │目的地址      │✓ 匹配成功    ││  │ │
│  │ │ │content.attack  │威胁名称      │⚠ 待确认     ││  │ │
│  │ │ └────────────────┴──────────────┴──────────────┘│  │ │
│  │ └──────────────────────────────────────────────────┘  │  │
│  │                                                        │  │
│  │ [✅ 确认映射表]  [💬 对话修改]  [📥 下载结果]        │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  💬 输入消息...                                      [发送▶] │
└─────────────────────────────────────────────────────────────┘
```

**交互逻辑**（Streamlit session_state 驱动）：
1. 文件上传 → st.file_uploader → 存储到 session_state["uploaded_file"]
2. 用户发送消息 → st.chat_input → Agent 处理 → st.chat_message 流式展示
3. 映射表展示 → st.data_editor → 用户编辑 → 回调 Agent 更新
4. 最终结果 → st.download_button → 返回 Base64 文件下载

---

### Phase 4：集成与测试

#### Step 4.1: 环境配置

```bash
# .env 文件
SILICONFLOW_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

#### Step 4.2: 依赖安装

```bash
# 根目录 requirements.txt
agno>=1.1.0
openai>=1.0.0
openpyxl>=3.1.0
pandas>=2.0.0

# web/requirements.txt
streamlit>=1.28.0
python-dotenv>=1.0.0
```

#### Step 4.3: 测试用例

| 测试编号 | 测试内容 | 预期结果 |
|----------|----------|----------|
| T1 | 上传有效 Base64 文件 | 解码成功，返回字段列表 |
| T2 | 上传无效 Base64 文件 | 返回错误提示 |
| T3 | 字段映射表生成 | 生成 Markdown 表格 |
| T4 | 用户确认映射表 | 执行映射，生成 Base64 |
| T5 | 用户修改映射表 | Agent 更新表格，重新渲染 |
| T6 | 下载最终结果 | 返回 Base64 文件 |

---

## 六、实施清单

| 阶段 | 步骤 | 任务 | 优先级 | 状态 |
|------|------|------|--------|------|
| Phase 1 | Step 1.1 | base64_tool.py — Base64 解码 + 字段提取 | ⭐⭐⭐ | 待开始 |
| Phase 1 | Step 1.2 | standard_mapper.py — 标准字段映射 + Excel 填充 | ⭐⭐⭐ | 待开始 |
| Phase 1 | Step 1.3 | base64_encoder.py — Base64 编码 | ⭐⭐⭐ | 待开始 |
| Phase 1 | Step 1.4 | file_tool.py — 文件读写工具 | ⭐⭐ | 待开始 |
| Phase 1 | Step 1.5 | 复制提示词到 agent/prompts/ | ⭐⭐ | 待开始 |
| Phase 1 | Step 1.6 | 复制标准字段.txt 到 agent/data/ | ⭐⭐ | 待开始 |
| Phase 2 | Step 2.1 | agent/agent.py — Agent 定义 | ⭐⭐⭐ | 待开始 |
| Phase 2 | Step 2.2 | 数据模型定义 (field_mapping.py, processing_result.py) | ⭐⭐ | 待开始 |
| Phase 3 | Step 3.1 | Streamlit 项目初始化 | ⭐⭐⭐ | 待开始 |
| Phase 3 | Step 3.2 | web/app.py — 主应用入口 | ⭐⭐⭐ | 待开始 |
| Phase 3 | Step 3.3 | web/components — 组件开发 | ⭐⭐⭐ | 待开始 |
| Phase 3 | Step 3.4 | 可编辑字段映射表格 (st.data_editor) | ⭐⭐⭐ | 待开始 |
| Phase 3 | Step 3.5 | 聊天消息展示 (st.chat_message) | ⭐⭐⭐ | 待开始 |
| Phase 3 | Step 3.6 | 文件上传与下载组件 | ⭐⭐⭐ | 待开始 |
| Phase 4 | Step 4.1 | 环境配置（.env） | ⭐⭐ | 待开始 |
| Phase 4 | Step 4.2 | 本地测试 (streamlit run) | ⭐⭐⭐ | 待开始 |
| Phase 4 | Step 4.3 | 部署 (streamlit share / Docker) | ⭐⭐⭐ | 待开始 |

---

## 七、风险与注意事项

### 7.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 标准字段表 654 行超上下文 | LLM 无法处理全部内容 | 分批传入，或使用模型支持更长上下文的版本 |
| SiliconFlow API 限流 | 请求失败 | 添加重试机制 + 限流保护 |
| 会话状态管理 | 多用户并发问题 | Streamlit 默认单用户，本地开发足够；生产环境可考虑 Redis |
| Base64 大文件 | 内存占用高 | 分块处理，控制单次处理文件大小 |

### 7.2 业务注意事项

1. **标准字段表全量传入**：这是硬性要求，需确保 LLM 上下文窗口足够
2. **Human-in-the-Loop 必要性**：Agent 生成的映射表需要用户确认，不可跳过
3. **Excel 填充逻辑**：使用 `config/对象.xlsx` 的"对应关系" Sheet 作为填充模板
4. **向后兼容**：保留现有的 tkinter GUI，作为备用入口

---

## 八、后续扩展方向

完成基础功能后，可考虑以下扩展：

1. **多文件批处理**：支持同时处理多个 Base64 文件
2. **映射模板管理**：用户可保存/加载自定义映射模板
3. **历史记录**：记录每次处理的映射历史
4. **导出格式扩展**：支持 JSON、XML 等多种导出格式
5. **多语言支持**：添加英文/日文等国际化支持

---

## 九、参考资源

- [Agno 官方文档](https://docs.agno.com/introduction)
- [SiliconFlow API 文档](https://docs.agno.com/models/providers/gateways/siliconflow/)
- [Streamlit 官方文档](https://docs.streamlit.io/)
- [标准字段映射提示词](./auto/phase2/标准字段.md)
- [强匹配提示词](./auto/phase2/提示词-强匹配.md)
- [威胁类型提示词](./auto/phase2/威胁类型.md)

---

*文档由 AI Agent 自动生成，如有问题请联系维护者。*
