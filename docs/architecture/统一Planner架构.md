# 统一 Planner 架构

```text
自然语言 ──> PlannerAgent ──> PlanDecision
                               ├─ Clarification/Guidance ──> Renderer
                               └─ ExecutePlan ──> PlanExecutor ──> StepAdapter
文件上传 ──> SessionState ──> Application 会话投影 ──> SessionFacts     ├─ 专业 Agent
按钮事件 ──> StepSpec ────────────────────────────────────┤
确定性清空 ──> Session                                    └─ 领域函数
```

`SessionFacts` 是 session 领域判断的唯一投影。`contracts/session_facts.py` 只定义不可变事实类型；`application/session_projection.py` 是读取会话、汇总可用字段、解析配置目标并生成安全产物目录的单一实现。Planner 只负责理解，Executor 只负责校验和推进，Adapter 只负责执行，Renderer 只负责展示。这些模块之间只传递 Pydantic 模型或明确 dataclass。

当前仅完成会话投影的 Application 归属；`PlanExecutor`、`SessionState` 和 Adapter 尚保留在 `web/`，将在后续迁移切片中调整。

`ExecutionReport` 是一次计划的结果账本。后续步骤通过 `step:<step_id>` 消费本次依赖，禁止读取旧 `last_enum_extract_result` 代替本次输入。任何步骤失败或待输入都会停止计划。

Fill、取消映射和配置导出必须携带显式配置来源。`session.decoded_config` 表示 Base64 上传后保留完整根结构的解码配置，`session.mapped_sub_rules` 表示字段映射后的子规则；执行器不得在两者之间隐式兜底。

权威决策见 `docs/adr/0005-independent-planner-agent.md`，产品门禁见 `docs/prd/unified-planner-routing.md`。
## 性能与进度边界

自然语言请求仍必须先调用一次 Planner。Planner 的应用层超时为 45 秒；超时或服务异常只返回安全追问，不回退旧关键词路由。按钮等确定性事件直接构造相同的 `StepSpec`，并复用 `PlanExecutor`。

字段映射的专业 Agent 是无工具的纯结构化 Agent。字段按首次出现顺序每 25 个一批，最多并发 3 批；每批通过 Agno `arun(stream=True, stream_events=True)` 执行，90 秒超时。只有超时、连接失败、HTTP 429 或 5xx 可以重试一次，默认等待 2 秒，`Retry-After` 最多采用 10 秒。执行器只消费 `RunCompleted` 的结构化内容，不消费部分 JSON 或隐藏推理。

多批结果先进入本次执行账本，并按批次序号恢复为原字段顺序。只有数量、字段名和类型全部校验通过后才允许写入 session；任一批次失败会取消其余批次，禁止部分写回。

## UI 与观测

核心层通过 `ProgressEvent` 和 `ProgressSink` 发布安全阶段。无 UI 时使用 `NullProgressSink`；Chainlit 使用一个持续更新的 `TaskList` 展示“理解指令、检索候选、处理第 N/M 批、校验写回、完成或失败”。超过 10 秒没有新阶段时只刷新等待时长，不展示模型推理或结构化 token。

模型边界日志使用 `MODEL_CALL_START/END/TIMEOUT`、`BATCH_START/END/RETRY` 和 `MODEL_USAGE`，包含 `plan_id`、`step_id`、批次、模型、数量、耗时、token 计数和稳定错误类别。字段检索 DEBUG 日志记录字段名、候选标准字段名与相似度分数（供字段映射优化分析），以及候选数量与耗时；仍禁止记录字段原值（日志取值）、API token、IP、日志样本和完整模型 JSON。

用户主动提交到自然语言入口的完整消息属于可审计输入，允许以明文写入应用日志；这是对上述敏感内容约束的显式例外，用户应自行确认消息中可记录的内容。Planner 完成后另记中文结构化意图摘要，只包含决策类型、业务操作名称及既有的数量/引用诊断，不展开步骤参数值。文件上传内容、认证信息、API 密钥和完整模型输出不适用此例外，仍不得新增写入日志。
