# 统一 Planner 架构

> **文档版本**：2026-08-31
> **架构决策**：ADR-0005、ADR-0006、ADR-0009

## 1. 统一入口

```text
自然语言 ──> application.request_runtime.run_user_request
                ├─ SessionState ──> session_projection ──> SessionFacts
                ├─ typed history ────────────────────────┐
                └─ user text ──> PlannerAgent ──> PlanDecision
                                                    │
                          Clarification / Guidance ─┤─> Web Renderer
                                                    │
                          ExecutePlan ──────────────> PlanExecutor
                                                        │
按钮事件 ──> run_deterministic_plan ────────────────────┤
                                                        ▼
                                              Application StepAdapter
```

自然语言请求恰好调用 Planner 一次；确定性 Action 与精确清空命令不调用 Planner。Planner 异常、输出非法、参数不足或意图冲突时安全停止，不回退关键词路由。

## 2. 角色边界

- **PlannerAgent**：读取用户原文、有限历史和安全 SessionFacts，输出严格 PlanDecision；不持有业务工具。
- **PlanExecutor**：校验 Session 语义、解析依赖、推进步骤、维护本次账本并执行后验证；不理解用户原文。
- **ExecutionPolicy**：注入分类特征字段、固定字段和目标范围等领域预检；不执行具体业务。
- **StepAdapter**：接收自包含 StepSpec，调用专业 Agent、Pipeline、领域函数或 Skill，并原子写回 Session。
- **Renderer**：只消费 PlanDecision 或 ExecutionReport，统一输出用户提示、表格和附件。

## 3. SessionFacts 与可引用会话产物

`contracts/session_facts.py` 只定义不可变事实类型；`application/session_projection.py` 是会话读取、字段汇总、配置目标绑定和安全产物目录的单一实现。

跨轮结果通过白名单来源显式引用：

- `session.artifacts.enum_values`
- `session.artifacts.threat_mapping`

真实值只保存在 SessionState 的类型化槽位中。Planner 只看到产物类型、数量、来源字段和唯一标准目标；遗留展示结构不能作为执行输入。主数据替换或清空会使可引用产物失效。

## 4. 执行不变量

- StepSpec.depends_on 只能引用此前 step_id，source_ref 必须与依赖一致。
- Threat Mapping 只消费用户显式值、本次 Enum Extract 产物或合法跨轮产物。
- Fill 必须声明 fill_kind、target_fields、source_ref 和 config_ref；成功时 changed_count > 0。
- 任一步 failed 或 needs_input 后立即停止。
- 每个 ExecutionReport 只渲染一次汇总；配置导出保持既有单文件语义。
- 配置来源不得在 decoded_config 与 mapped_sub_rules 之间隐式兜底。

## 5. 字段映射策略

FieldMappingBatchRunner 的冻结策略：

- 按首次出现顺序去重；
- 每批 25 个字段，最多并发 3 批；
- 每批 90 秒超时；
- 仅超时、连接失败、HTTP 429 或 5xx 重试一次；
- 默认等待 2 秒，Retry-After 最多 10 秒；
- 超时批次拆分一次，漏字段补查；
- 批次结果按原字段顺序恢复；
- 全部数量、字段名和类型校验通过后才写 Session。

任一批次失败会取消其余批次，禁止部分写回。物理迁移没有改变模型调用阶段或执行策略。

## 6. 进度与观测

Application 通过 Contracts 的 ProgressEvent/ProgressSink 发布安全阶段；无 UI 时使用 NullProgressSink，Chainlit 使用 TaskList。模型边界保留 MODEL_CALL、BATCH、RETRY 和 MODEL_USAGE 等结构化事件，携带 plan_id、step_id、批次、模型、数量、耗时、token 与稳定错误类别。

不得记录字段原值、API token、真实路径、日志样本或完整模型 JSON。用户主动提交的自然语言是既有明文审计例外；认证信息和文件内容仍受脱敏约束。

## 7. 权威文档

- [ADR-0005：独立 PlannerAgent](../adr/0005-independent-planner-agent.md)
- [ADR-0006：可引用会话产物](../adr/0006-referenceable-session-artifacts.md)
- [ADR-0009：Application 运行时归属](../adr/0009-application-runtime-ownership.md)
- [统一 Planner PRD](../prd/unified-planner-routing.md)
