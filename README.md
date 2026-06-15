# ToolWithAgent — 数据映射智能助手

基于 AI Agent 的安全日志字段映射、威胁类型分析和日志解析工具。交付形式为 **Chainlit Web 聊天界面**（桌面 GUI 已归档至 `reference/gui/`）。

## 核心功能

| 功能 | 说明 |
|------|------|
| **标准字段映射** | 异构日志字段 → 统一标准字段（Levenshtein 编辑距离 + BM25 混合检索） |
| **威胁类型标准化** | 告警威胁类型归一化到威胁知识库 |
| **枚举提取/填充** | 从日志提取映射规则词对，或批量填充枚举映射表 |
| **日志格式识别** | LLM 识别日志数据结构类型（JSON/CSV/CEF/KeyValue/Header+JSON 等） |
| **日志特征分类** | 提取字段统计特征（field_name, value_count, data_type, sample_values） |
| **结构化指纹知识库** | 基于 ChromaDB 向量索引，相似格式快速匹配复用 |

## 项目结构

```
toolswithagent/
├── main.py                          # 桌面应用入口（Tkinter，已归档）
├── requirements.txt                 # Python 依赖
├── chainlit.md                      # Chainlit 配置
├── CHANGELOG.md                     # 变更日志
│
├── web/                             # Chainlit Web 界面
│   ├── chainlit_app.py              # 薄入口（~60行）：生命周期钩子 + 转发
│   ├── start_handler.py             # @cl.on_chat_start 实现
│   ├── settings_handler.py          # @cl.on_settings_update 实现
│   ├── message_router.py            # @cl.on_message 路由分发
│   ├── upload_handlers.py           # 文件上传处理（含 Excel 检测）
│   ├── user_message_handlers.py     # 用户文本消息处理
│   ├── log_parser_handler.py        # 日志解析 Pipeline（独立）
│   ├── action_callbacks.py          # 9个 Action 回调（按钮交互）
│   ├── utils.py                     # 纯辅助函数（JSON 解析、渲染）
│   ├── global_state.py              # 全局状态管理
│   ├── route_config.py              # 路由关键词匹配（字段映射/威胁/枚举/日志解析）
│   ├── llm_client.py                # LLM 客户端（Team 调用 + CircuitBreaker）
│   ├── input_builder.py             # LLM 输入构造
│   ├── response_handler.py          # 响应解析 + cl.Dataframe 渲染
│   ├── threat_handler.py            # 威胁填充模式分流
│   ├── enum_handler.py              # 枚举填充/提取分流
│   ├── file_handler.py              # 底层文件处理（数据层）
│   ├── parsers.py                   # JSON 解析
│   ├── session_state.py             # 会话状态管理
│   └── model_manager.py             # 模型管理
│
├── agent/                           # AI Agent 系统
│   ├── core/                        # 核心层
│   │   ├── team.py                  # Agno Team 定义（Route Mode）
│   │   ├── model_config.py          # 多 Provider 模型配置（SiFlow/DeepSeek）
│   │   ├── resilience.py            # CircuitBreaker + ModelFallback + RetryPolicy
│   │   ├── prompts.py               # .md Prompt 加载器
│   │   ├── field_retriever.py       # BM25 + 向量混合检索
│   │   └── tracing.py               # OpenTelemetry 请求追踪
│   ├── tools/                       # Agent 工具集
│   │   ├── field_mapping_tool.py    # 字段映射工具
│   │   ├── threat_mapping_tool.py   # 威胁类型匹配工具
│   │   ├── enum_extract_tool.py     # 枚举提取工具
│   │   ├── enum_field_tool.py       # 枚举填充工具
│   │   ├── base64_tool.py           # Base64 编解码
│   │   ├── log_parser_pipeline.py   # 日志解析管道（4-step）
│   │   └── log_pattern_store.py     # 日志模式知识库
│   ├── shared/                      # 共享算法
│   │   ├── field_mapping.py         # Levenshtein 编辑距离核心
│   │   ├── threat_fill.py           # 威胁填充逻辑
│   │   ├── base64_encode_decode.py  # Base64 核心
│   │   └── logger.py                # 统一日志
│   └── prompts/                     # LLM Prompt 模板（.md 文件）
│       ├── log_format_identify.md   # Step 1：日志格式识别
│       └── log_classify_feature.md  # Step 3：日志特征分类
│
├── config/                          # 共享配置
│   ├── route_keywords.json          # 路由关键词
│   ├── threat_type_config.json      # 威胁类型映射配置
│   ├── 标准字段.txt                 # 标准字段列表
│   └── 对象.xlsx                    # 系统属性映射表
│
├── docs/                            # 项目文档
│   ├── architecture/                # 架构文档
│   │   ├── 20260514_架构概览.md     # 系统架构全景图
│   │   └── 20260514_代码级设计说明.md # 模块依赖/函数签名/算法/数据流
│   └── 文档维护规范.md              # 文档编写与维护标准
│
└── reference/gui/                   # 桌面 GUI 归档（不再维护）
```

## 快速开始

### 环境要求

- Python 3.9+
- SiliconFlow API Key（需设置环境变量 `SILICONFLOW_API_KEY`）

### 安装

```bash
pip install -r requirements.txt
```

### 启动 Web 界面

```bash
chainlit run web/chainlit_app.py
```

启动后访问 `http://localhost:8000`，在聊天界面：
1. **上传** Excel 或粘贴日志数据
2. **输入指令**：`字段映射` / `威胁类型` / `枚举提取` / `枚举值填充` / `日志解析`
3. Agent 自动识别意图并完成处理

### 环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `SILICONFLOW_API_KEY` | SiliconFlow API 密钥 | 是 |
| `SILICONFLOW_BASE_URL` | SiliconFlow 端点 | 否 |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 否（故障转移用） |
| `CHROMADB_PATH` | ChromaDB 存储路径 | 否 |

可通过 `.env` 文件配置或直接设置系统环境变量。

## 文档导航

| 文档 | 内容 |
|------|------|
| [架构概览](docs/architecture/20260514_架构概览.md) | 系统架构图、核心流程、外部依赖、错误处理策略 |
| [代码级设计说明](docs/architecture/20260514_代码级设计说明.md) | 模块依赖图、函数签名、关键算法、数据流、配置结构 |
| [chainlit_app模块说明](docs/architecture/chainlit_app模块说明.md) | Web UI 层模块职责、调用关系、数据流 |
| [CHANGELOG](CHANGELOG.md) | 按版本整理的完整变更记录 |
| [项目概要](docs/20260514_项目概要.md) | 项目背景、目标、功能全景 |
| [文档维护规范](docs/文档维护规范.md) | 文档编写、命名、更新标准 |

## 重构历史

### 2026-06-12 - chainlit_app.py 重构

**目标**：提升代码可读性和可维护性

**变更**：
- 将 1400 行的 `chainlit_app.py` 拆分为 9 个平级模块
- 主文件精简至 60 行（减少 96%）
- 保持向后兼容，无需修改已有业务代码

**新增模块**：
- `start_handler.py` - 聊天开始初始化
- `settings_handler.py` - 模型设置更新
- `message_router.py` - 消息路由分发
- `upload_handlers.py` - 文件上传处理
- `user_message_handlers.py` - 用户文本消息处理
- `log_parser_handler.py` - 日志解析 Pipeline
- `action_callbacks.py` - Action 回调（按钮交互）
- `utils.py` - 纯辅助函数
- `global_state.py` - 全局状态管理

**详细文档**：
- [重构方案](chainlit_app重构方案.md)
- [完成报告](chainlit_app重构方案_完成版.md)

## 技术栈

- **Agent 框架**：Agno (Team Route Mode, 4+ MemberAgents)
- **LLM Provider**：SiliconFlow (主) / DeepSeek (备用)，含 CircuitBreaker 熔断
- **Web 界面**：Chainlit
- **向量检索**：ChromaDB + BM25 混合检索
- **可观测性**：OpenTelemetry