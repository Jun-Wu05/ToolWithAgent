# ToolWithAgent — 数据映射智能助手

基于 AI Agent 的安全日志字段映射、威胁类型分析和日志解析工具。交付形式为 **Chainlit Web 聊天界面**。

## 核心功能

| 功能 | 说明 |
|------|------|
| **标准字段映射** | 异构日志字段 → 统一标准字段（Embedding 语义检索 + 中文同义词桥接） |
| **威胁类型标准化** | 告警威胁类型归一化到威胁知识库 |
| **枚举提取/填充** | 从日志提取映射规则词对，或批量填充枚举映射表 |
| **日志格式识别** | LLM 识别日志数据结构类型（JSON/CSV/CEF/KeyValue/Header+JSON 等） |
| **日志特征分类** | 提取字段统计特征（field_name, value_count, data_type, sample_values） |
| **结构化指纹知识库** | 基于 ChromaDB 向量索引，相似格式快速匹配复用 |

## 项目结构

```
toolswithagent/
├── requirements.txt                 # Python 依赖
├── chainlit.md                      # Chainlit 界面说明
├── CHANGELOG.md                     # 变更日志
│
├── web/                             # Chainlit Web 界面
│   ├── chainlit_app.py              # 薄入口：生命周期钩子 + 转发
│   ├── start_handler.py             # @cl.on_chat_start 实现
│   ├── settings_handler.py          # @cl.on_settings_update 实现
│   ├── message_router.py            # @cl.on_message 路由分发
│   ├── file_handlers.py             # Chainlit 文件上传适配（Excel 检测与用户反馈）
│   ├── user_message_handlers.py     # 用户文本消息处理（一次 Planner 调用 + Executor + 渲染）
│   ├── action_callbacks.py          # Action 回调（按钮交互）
│   ├── plan_executor.py             # 计划执行器（依赖账本、失败停止）
│   ├── adapters/                    # Application Adapter 的 Web 兼容重导出
│   ├── execution_adapters.py        # 兼容垫片：重导出 Application 公共入口
│   ├── session_state.py             # 会话状态（SessionState）
│   ├── field_source.py              # 字段映射的真实日志字段来源
│   ├── input_builder.py             # 字段映射批次 LLM 输入构造（embedding 候选）
│   ├── parsers.py                   # 模型输出 JSON 解析
│   ├── plan_renderer.py             # 统一渲染器（Clarification/ExecutionReport）
│   ├── deterministic_plan.py        # 按钮入口的类型化计划
│   ├── history_store.py             # 受限对话历史
│   ├── chainlit_progress.py         # 进度事件的 Chainlit 展示
│   ├── llm_client.py / model_manager.py    # LLM 客户端与模型管理
│   └── utils.py / global_state.py / constants.py  # 辅助函数
│
├── application/                     # 无 Chainlit 依赖的应用运行时
│   ├── file_input.py                # Base64/JSON/TXT 解码与主数据原子提交
│   ├── session_state.py             # 主数据及会话生命周期
│   ├── execution.py                 # PlanExecutor / ExecutionContext
│   └── adapters/                    # 全部业务适配器与唯一生产组合入口
│
├── contracts/                       # 框架无关类型契约（web → contracts ← agent）
│   ├── planner_models.py            # PlanDecision / StepSpec / Artifact 类型契约
│   ├── session_facts.py             # SessionFacts 投影（Planner 输入）
│   └── progress.py                  # 进度事件抽象（不依赖 Chainlit）
│
├── agent/                           # AI Agent 系统
│   ├── core/                        # 核心层
│   │   ├── team.py                  # Agno Team 与专业 Agent 构造
│   │   ├── planner.py               # 独立 PlannerAgent（ADR-0005）
│   │   ├── agent.py                 # 上传解码兼容入口与历史 simple_encode
│   │   ├── model_config.py          # 多 Provider 模型配置（SiFlow/DeepSeek）
│   │   ├── resilience.py            # CircuitBreaker + ModelFallback + RetryPolicy
│   │   ├── prompts.py               # Pipeline Prompt 的迁移期兼容重导出
│   │   ├── field_retriever.py       # Embedding 语义检索（中文同义词 + tag 规则 + 精确匹配）
│   │   └── tracing.py               # OpenTelemetry 请求追踪
│   ├── tools/                       # Agent 工具集
│   │   ├── standard_mapper.py       # 字段映射工具
│   │   ├── enum_field_tool.py       # 枚举映射表读取
│   │   ├── base64_tool.py           # Base64 编解码
│   │   ├── rule_generator/          # 解析规则生成（入口/子规则、字段映射回写）
│   │   ├── pipeline/                # 日志解析 Pipeline（格式识别/特征定位/分类）
│   │   └── log_pattern_store.py     # 日志模式知识库
│   ├── shared/                      # 共享算法
│   │   ├── field_mapping.py         # 字段映射核心算法
│   │   ├── threat_fill.py           # 威胁填充逻辑
│   │   └── logger.py                # 统一日志
│   └── prompts/                     # 全部 LLM Prompt 模板与公开加载器
│       ├── planner.md               # PlannerAgent 指令
│       ├── threat_type.md           # ThreatAgent 指令
│       └── log_*.md / kv_*.md       # 日志解析 Pipeline 各步指令
│
├── config/                          # 共享配置
│   ├── threat_type_config.json      # 威胁类型映射配置
│   ├── field_synonyms.json          # 字段同义词表（en/zh 双字段，缩写展开 + 中文桥接）
│   ├── tag_rules.json               # 字段标签规则（token 级匹配）
│   ├── knowledge_base/              # 实体模式与合并报告
│   ├── 标准字段.txt / 空规则.txt     # 标准字段列表（625条）等
│   └── 对象.xlsx                    # 系统属性映射表
│
├── evaluation/                      # 真实模型语义评测
│   └── planner_semantic_eval.py     # Planner 语义稳定性评测脚本
│
├── tests/                           # 离线回归测试（pytest）
│
└── docs/                            # 项目文档
    ├── adr/                         # 架构决策记录（ADR-0001 ~ 0005）
    ├── architecture/                # 架构概览、代码级设计、统一 Planner 架构、测试场景手册等
    ├── prd/                         # 产品需求文档
    └── agents/                      # Agent 工作流说明（issue 跟踪 / triage 标签 / 领域文档）
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
1. **上传** Excel 或粘贴日志数据。数据表 Excel 必须包含"**原始日志**"列，否则上传将被拒绝并提示重新上传正确格式（枚举映射表 Excel 不受此限制）
2. **输入指令**：`字段映射` / `威胁类型` / `枚举提取` / `枚举值填充` / `日志解析`，单一意图或复合意图均可
3. 独立 PlannerAgent 识别意图并生成类型化计划，PlanExecutor 按依赖链执行并一次汇总渲染（见 ADR-0005）

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
| [CONTEXT.md](CONTEXT.md) | 领域术语表（映射/填充/解析规则等核心概念与角色边界） |
| [架构概览](docs/architecture/架构概览.md) | 系统架构图、核心流程、外部依赖、错误处理策略 |
| [统一Planner架构](docs/architecture/统一Planner架构.md) | 独立 PlannerAgent + PlanExecutor 架构说明 |
| [代码级设计说明](docs/architecture/代码级设计说明.md) | 模块依赖图、函数签名、关键算法、数据流、配置结构 |
| [chainlit_app模块说明](docs/architecture/chainlit_app模块说明.md) | Web UI 层模块职责、调用关系、数据流 |
| [测试场景手册](docs/architecture/测试场景手册.md) | 冒烟测试场景与预期 |
| [ADR](docs/adr/0005-independent-planner-agent.md) | 架构决策记录（最新：ADR-0005 独立 PlannerAgent） |
| [PRD](docs/prd/unified-planner-routing.md) | 产品需求文档（最新：统一 Planner 路由） |
| [CHANGELOG](CHANGELOG.md) | 按版本整理的完整变更记录 |
| [项目概要](docs/architecture/项目概要.md) | 项目背景、目标、功能全景 |
| [文档维护规范](docs/architecture/文档维护规范.md) | 文档编写、命名、更新标准 |

## 技术栈

- **Agent 框架**：Agno (Team Route Mode, 4+ MemberAgents)
- **LLM Provider**：SiliconFlow (主) / DeepSeek (备用)，含 CircuitBreaker 熔断
- **Web 界面**：Chainlit
- **向量检索**：SiliconFlow Embedding API（Qwen3-Embedding-8B）+ 中文同义词桥接 + token 重排序
- **可观测性**：OpenTelemetry
