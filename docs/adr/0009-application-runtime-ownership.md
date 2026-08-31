# ADR-0009：Application 运行时归属与单向依赖

- 状态：已接受
- 日期：2026-08-31
- 关联：父 PRD #130；实施 Issues #132～#144；ADR-0005、ADR-0006、ADR-0008

## 背景

独立 PlannerAgent、类型化计划、PlanExecutor、StepAdapter、SessionFacts 和可引用会话产物已经建立正确的业务执行模型，但最初的物理归属仍以 Chainlit Web 为中心：无 Chainlit 依赖的执行器、会话、历史、字段输入和 Adapter 实现位于 Web，Contracts 曾反向读取运行时事实，Prompt 加载与文件解码也分散在误导性的包中。

这种结构让目录无法表达真实职责，并形成 Contracts、Web 与 Agent 之间的反向依赖。替换界面入口、定位执行策略或验证会话生命周期时，维护者必须先理解 Chainlit 接线才能找到应用运行时。

## 决策

新增并深化顶层 `application/` 包，作为与 Chainlit 解耦的应用运行时所有者。

### Application 核心

- `request_runtime.py` 统一自然语言请求、确定性计划和清空命令；自然语言请求保持恰好一次 Planner 调用。
- `execution.py` 拥有 ExecutionContext、PlanExecutor、StepAdapter 协议、依赖账本和失败关闭。
- `session_state.py`、`session_projection.py`、`history.py` 拥有主数据生命周期、安全事实投影和受限历史。
- `progress.py` 提供无 UI 进度实现；`file_input.py`、`model_runtime.py`、`field_runtime.py` 提供文件、模型和字段公共入口。
- 核心运行时只依赖 Contracts 与标准库。领域预检通过 ExecutionPolicy 注入，不把 Agent、Pipeline 或 Chainlit 依赖带入核心。

### Application Adapters

`application/adapters/` 承载全部生产 StepAdapter，`create_default_adapters(team)` 是唯一组合入口。Adapters 可在明确接缝处依赖专业 Agent、领域函数、Pipeline 和 Skills；它们接收自包含 StepSpec，不理解用户原文，不从未声明 Session 键兜底，并在校验完成后原子写回。

FieldMappingBatchRunner 单独拥有分批、并发、超时拆批、重试、Retry-After、漏字段补查、去重和顺序恢复策略。Adapter 只保留步骤翻译、进度、产物、事件名称标注和 Session 提交。

### Web 与 Contracts

Web 只保留 Chainlit 输入、生命周期、每会话锁、设置、进度、结果渲染和用户反馈。Contracts 只保留 PlanDecision、StepSpec、ExecutionReport、SessionFacts、可引用产物和 ProgressEvent 等类型与不变量，不读取运行时状态。

允许的依赖方向为：

```text
web → application → contracts
          │
          └─ adapters → agent / domain / skills
```

Application、Contracts、Agent 和 Skills 禁止反向导入 Web 或 Chainlit。

### 迁移兼容边界

迁移期旧入口只允许重导出新模块的同一对象，不保留第二份实现；新生产代码不得继续导入旧路径。内部生产、动态注册、包级重导出、测试和已知外部 Python 依赖全部归零后，兼容入口必须在本阶段删除。本轮临时 Web 执行器、会话、适配器、历史、字段输入和旧 Prompt 入口已经删除。

既有 Base64 Tool、Web constants 和日志桥状态不属于本次迁移兼容入口，不因疑似无调用而顺手删除；其证据审计属于第二阶段。

### 零行为变化

物理迁移不得改变：

- 类型化计划语义、Planner 与专业 Agent 调用阶段或次数；
- 字段映射批大小、并发、超时、重试、补查和原子写回；
- Session 主数据、附件、派生配置和可引用会话产物生命周期；
- 稳定错误码、安全日志、追踪字段、Token 桥接和进度心跳；
- Chainlit 生命周期、十个 Action callback、按钮、提示、表格和交互；
- JSON/Base64 根结构、键顺序、中文编码、下载文件名和配置语义。

## 后果

### 正面

- 目录直接表达 Chainlit 适配、应用编排、类型契约和领域实现的边界。
- CLI、HTTP 或测试入口可复用 Application，而不引入 Chainlit。
- 执行策略和 Session 生命周期有单一所有者，静态依赖门禁可阻止回退。
- 每条业务链路可以通过 Application 公共接口和可控 Adapter 进行离线验证。

### 负面

- Application Adapters 仍需要连接 Agent 与领域实现，因此 `application/` 不是完全纯净的领域层；核心与 Adapter 子层必须继续分开审视。
- 迁移后的文件数量增加，维护者需要按语义层而不是只按目录深度阅读。
- 外部若曾依赖未承诺的 Web 私有模块，需要迁移到 Application 公共入口；仓库外调用审计未发现此类依赖。

## 与既有 ADR 的关系

- ADR-0005 的 Planner、Executor、Adapter 角色和行为不变量继续有效；本 ADR 固化其最终物理归属。
- ADR-0006 的可引用会话产物语义继续有效，真实 Session 所有者现为 Application。
- ADR-0008 的 Skills 单一事实源和类型化接线继续有效，FieldSkillAdapter 现位于 Application。
- ADR-0001～ADR-0004 记录架构演进。它们正文中的 Web 文件路径、Router/关键词入口和迁移期实现属于当时历史，不再代表当前生产路径；保留原文以维护决策历史。
