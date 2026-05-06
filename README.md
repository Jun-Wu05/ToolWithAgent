# ToolWithAgent

安全设备日志字段映射与威胁类型分析智能工具，基于 AI 智能体（Agent）+ Web 交互界面（GUI 已归档至 reference/gui/）。

## 📁 项目结构

```
├── README.md                    # 项目说明
├── main.py                      # 桌面应用入口（Tkinter GUI）
├── requirements.txt             # Python 依赖
├── chainlit.md                  # Chainlit Web 配置
├── .gitignore
│
├── agent/                       # 🤖 AI 智能体系统
│   ├── core/                    # Agent 核心（模型配置、提示词加载、Team、熔断器、链路追踪）
│   ├── tools/                   # Agent 工具集（Base64 编解码、字段映射、威胁类型、枚举处理）
│   ├── prompts/                 # 业务提示词（字段映射、威胁类型、枚举字段）
│   ├── memory/                  # 会话管理
│   ├── data/                    # 标准字段表
│   └── agent.py                 # Agent 定义入口
│
├── agent/shared/                # 🔧 Agent 共享工具（从 GUI 迁移）
│   ├── __init__.py
│   ├── logger.py                # 日志模块
│   ├── field_mapping.py         # 字段映射处理
│   └── threat_fill.py           # 威胁类型填充
│
├── web/                         # 🌐 Web 交互界面（Chainlit）
│   ├── chainlit_app.py          # Web 应用入口
│   ├── config.py                # Web 配置
│   ├── llm_client.py            # LLM 客户端（Team 调用 + 意图直接路由 + 超时保护）
│   ├── input_builder.py         # 输入构建
│   ├── enum_handler.py          # 枚举处理
│   ├── threat_handler.py        # 威胁类型处理
│   ├── response_handler.py      # 响应处理
│   ├── route_config.py          # 路由配置（关键词预筛）
│   ├── session_state.py         # 会话状态管理
│   ├── parsers.py               # 数据解析
│   └── utils.py                 # 工具函数
│
├── reference/gui/               # 📦 桌面 GUI 归档（仅逻辑参考，不再维护）
│   ├── handlers/                # 各功能模块处理器
│   ├── data_processor.py        # 数据处理核心
│   ├── gui_handler.py           # GUI 界面分发
│   ├── field_mapping_handler.py # 字段映射处理
│   ├── threat_fill_handler.py   # 威胁类型填充
│   ├── threat_type_manager.py   # 威胁类型管理
│   └── logger.py                # 日志模块
│
├── config/                      # ⚙️ 共享配置
│   ├── 对象.xlsx                # 系统属性映射表
│   ├── threat_type_config.json  # 威胁类型配置
│   └── threat_nomal.txt         # 威胁类型参考
│
├── docs/                        # 📚 项目文档
│   ├── readme.md                # 桌面工具详细说明
│   ├── 代码优化.md
│   ├── 威胁类型映射与字段处理完整指南.md
│   └── skill.md
│
```

## 🚀 快速开始

### 环境要求

- Python 3.9+
- Windows / macOS / Linux

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行方式

#### 1. 桌面 GUI 应用

> ⚠️ **已归档**：桌面 GUI 代码已移至 `reference/gui/`，仅供逻辑参考，不再维护。

```bash
python main.py
```

提供功能：Base64 编解码、字段映射、威胁类型填充、CSV 格式转换、标准字段映射。

#### 2. Web 交互界面（Chainlit）

```bash
chainlit run web/chainlit_app.py
```
启动后访问 `http://localhost:8000` 与 AI Agent 进行对话式交互。

#### 3. 命令行/API

```python
from agent import create_agent

agent = create_agent()
response = agent.run("解码这个 Base64 数据...")
```


## 🔧 功能概览

| 功能 | 桌面应用 | AI Agent | Web 界面 |
|------|:---:|:---:|:---:|
| Base64 编解码 | ✅ | ✅ | ✅ |
| 标准字段映射 | ✅ | ✅ | ✅ |
| 威胁类型标准化 | ✅ | ✅ | ✅ |
| 枚举字段批量处理 | ✅ | ✅ | ✅ |
| 字段映射集合（功能5） | 📦 | - | - |
| Base64 错误检测 | 📦 | - | - |
| CSV 格式转换 | 📦 | - | - |
| 对话式交互 | - | ✅ | ✅ |
| 自主推理与任务规划 | - | ✅ | ✅ |

## 📝 模型配置

Agent 使用 SiliconFlow 平台的 DeepSeek-V3.2 模型。在环境变量中配置：

```bash
export SILICONFLOW_API_KEY="your-api-key"
export SILICONFLOW_MODEL="deepseek-ai/DeepSeek-V3.2"  # 可选