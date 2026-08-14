# PRD：统一 Planner 正确处理用户指令

## 问题与目标

用户的业务指令必须结合当前 session 理解，而不是由关键词决定。系统需要让同一句“枚举值处理”在无数据、只有日志、已有枚举映射表与子规则等上下文中得到安全且不同的决策，并支持 Enum Extract → Threat Mapping → Fill 的显式数据流。

## 必须交付

1. 所有自然语言业务请求先经过独立 PlannerAgent，Planner 失败、结构非法或语义不足时明确追问且不执行。
2. 所有业务操作使用类型化 `StepSpec` 经统一 PlanExecutor 执行，本次步骤只能消费声明的本次依赖，Fill 必须验证目标字段真实变化。
3. 文件和按钮等确定性事件建立相同领域事实或类型化计划；删除关键词早退、`[PLAN:...]`、原文猜参和会劫持下一条消息的 fill mode。

## 实现决策

- `web/planner_models.py` 定义 `PlanDecision`、七种 `StepSpec`、`StepResult` 和 `ExecutionReport`。
- `web/session_facts.py` 是 session 状态判断的唯一投影模块，不暴露密钥、路径和原始载荷。
- `agent/core/planner.py` 构造无业务工具的 Agno Agent，并通过 `output_schema=PlanDecision` 强制结构。
- `web/plan_executor.py` 不 import Chainlit，集中校验、依赖账本、停止规则和结果验证。
- `web/execution_adapters.py` 连接专业 Agent 和领域函数；适配器不接收用户原文。
- `web/user_message_handlers.py` 只承担输入适配、一次 Planner 调用、Executor 调用和报告渲染。
- 参见 ADR-0005。

## 测试决策

- 离线测试替换 Planner/专业 LLM 和 Chainlit sink，不 mock PlanExecutor 或真实枚举填充核心。
- 覆盖同文不同 session、意图冲突、Planner 异常、非法 schema、缺失字段、失败停止、未声明依赖、依赖类型错误、零变更失败与单次汇总。
- 对 `SessionFacts` 做敏感值泄漏测试；对跨模块模型做 Pydantic 严格契约测试。
- 对本次核心 Python 模块做 AST 静态检查，新增/修改模块、类、公共函数的 docstring 必须含中文，新增行内注释不得为纯英文。
- 发布前运行完整 `pytest`；真实模型语料在 Web 环境每条连续运行三次并记录延迟/token。

## 验收场景

- 无数据 +“枚举值处理”→ Clarification，不调用执行器。
- 只有日志 + 同一句话 → 询问目标字段。
- 枚举映射表 + 已映射子规则 + 同一句话 → 一步 Enum Fill，`normalize.mappings` 变化并生成配置产物。
- “提取 event_type3 的枚举值”→ 一步 Enum Extract；字段不存在时执行前拦截。
- 已有旧枚举结果 +“把这些值做威胁映射”→ 不使用旧结果，必须追问或依赖本次步骤。
- 三步复合指令 → 本次账本依次传递 enum_values、threat_mapping、config_export。
- 两步复合指令“提取 alarm_name 的枚举值，并进行威胁类型映射”（未提填充）→ `enum_extract → threat_mapping` 依赖链，不生成 fill；威胁映射使用内置威胁分类表，会话没有枚举映射表时也必须执行而非追问（回归 #79）。
- 意图冲突 → Clarification；帮助请求 → Guidance；均不调用业务执行器。
