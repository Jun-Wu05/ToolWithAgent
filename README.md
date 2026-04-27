# ToolWithAgent

安全设备配置规则数据映射智能工具，集成了桌面 GUI 应用、AI 智能体（Agent）和 Web 交互界面。

## 📁 项目结构

```
├── README.md                    # 项目说明
├── main.py                      # 桌面应用入口（Tkinter GUI）
├── requirements.txt             # Python 依赖
├── chainlit.md                  # Chainlit Web 配置
├── .gitignore
│
├── agent/                       # 🤖 AI 智能体系统
│   ├── core/                    # Agent 核心（模型配置、提示词加载、Team）
│   ├── tools/                   # Agent 工具集（Base64 编解码、字段映射、威胁类型、枚举处理）
│   ├── prompts/                 # 业务提示词（字段映射、威胁类型、枚举字段）
│   ├── memory/                  # 会话管理
│   ├── data/                    # 标准字段表
│   └── agent.py                 # Agent 定义入口
│
├── src/                         # 🖥️ 桌面应用
│   ├── handlers/                # 各功能模块处理器
│   ├── data_processor.py        # 数据处理核心
│   ├── gui_handler.py           # GUI 界面分发
│   ├── field_mapping_handler.py # 字段映射处理
│   ├── threat_fill_handler.py   # 威胁类型填充
│   ├── threat_type_manager.py   # 威胁类型管理
│   └── logger.py                # 日志模块
│
├── web/                         # 🌐 Web 交互界面（Chainlit）
│   ├── chainlit_app.py          # Web 应用入口
│   ├── config.py                # Web 配置
│   ├── handlers.py              # Web 消息处理
│   ├── interaction.py           # 交互逻辑
│   ├── parsers.py               # 数据解析
│   └── utils.py                 # 工具函数
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
└── archive/                     # 📦 归档（历史实验代码和文档）
    ├── auto/                    # 实验脚本（phase1-4 + allinone）
    ├── plan/                    # 历史设计文档
    ├── 测试数据/                 # 历史测试数据
    ├── scripts/                 # 历史辅助脚本
    └── public/                  # 历史前端组件
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

```bash
python main.py
```

提供功能：Base64 编解码、字段映射、威胁类型填充、CSV 格式转换、标准字段映射。

#### 2. AI Agent（命令行/API）

```python
from agent import create_agent

agent = create_agent()
response = agent.run("解码这个 Base64 数据...")
```

#### 3. Web 交互界面（Chainlit）

```bash
chainlit run web/chainlit_app.py
```

启动后访问 `http://localhost:8000` 与 AI Agent 进行对话式交互。

## 🔧 功能概览

| 功能 | 桌面应用 | AI Agent | Web 界面 |
|------|:---:|:---:|:---:|
| Base64 编解码 | ✅ | ✅ | ✅ |
| 标准字段映射 | ✅ | ✅ | ✅ |
| 威胁类型标准化 | ✅ | ✅ | ✅ |
| 枚举字段批量处理 | ✅ | ✅ | ✅ |
| 字段映射集合（功能5） | ✅ | - | - |
| Base64 错误检测 | ✅ | - | - |
| CSV 格式转换 | ✅ | - | - |
| 对话式交互 | - | ✅ | ✅ |
| 自主推理与任务规划 | - | ✅ | ✅ |

## 📝 模型配置

Agent 使用 SiliconFlow 平台的 DeepSeek-V3.2 模型。在环境变量中配置：

```bash
export SILICONFLOW_API_KEY="your-api-key"
export SILICONFLOW_MODEL="deepseek-ai/DeepSeek-V3.2"  # 可选