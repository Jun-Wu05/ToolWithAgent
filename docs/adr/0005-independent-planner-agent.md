# ADR-0005：独立 PlannerAgent 与自然语言统一入口

- 状态：已接受
- 日期：2026-08-12
- 关联：覆盖 ADR-0002 的自然语言快路径，细化 ADR-0004；可引用会话产物由 ADR-0006 补充

## 背景

自然语言请求曾先由 `detect_intent` 扫描关键词，再分别进入枚举、威胁、日志和填充 handler。相同文本在不同 session 下需要不同含义，例如已存在枚举映射表和子规则时，“枚举值处理”应执行枚举填充，却会在理解层之前被枚举提取快路径截获。旧 `[PLAN:...]` 文本协议还会丢失字段、来源和步骤依赖，并允许执行器重新从原文猜参。

## 决策

引入无业务工具的独立 `PlannerAgent`。所有自然语言业务请求恰好调用 Planner 一次，输入只有用户原文、最近六条对话和不可变 `SessionFacts`。Planner 使用 Agno/Pydantic `output_schema` 返回严格 `PlanDecision`：`ExecutePlan`、`Clarification` 或 `Guidance`。

执行计划由无 Chainlit 依赖的 `PlanExecutor.execute(plan, context)` 处理。Executor 统一负责 session 语义校验、依赖解析、步骤推进、结果账本和执行后验证。专业 Agent 与领域函数只是 `StepAdapter`，不得理解原文或读取未声明的旧 `last_*` 作为本次输入。

确定性清空事件可直接执行；文件上传只建立结构化 session 事实；按钮将完整参数转换为 `StepSpec` 后复用 PlanExecutor。Planner 服务异常、输出非法、参数不足或意图冲突时必须追问并停止，禁止回退关键词路由。

## 公共不变量

- `SessionFacts` 不包含 API key、真实文件路径或原始敏感值。
- `StepSpec.depends_on` 只引用此前 `step_id`；`source_ref` 必须与依赖一致。
- 威胁映射只消费用户显式值或本次枚举步骤产物。
- Fill 必须声明 `fill_kind`、`target_fields`、`source_ref`，成功时 `changed_count > 0`。
- 任一步 `needs_input` 或 `failed` 后立即停止。
- Renderer 只渲染一次步骤汇总和最多一个最终配置文件。
- 新增或修改的注释与 docstring 使用中文，解释设计原因和不变量。

## 取舍

自然语言请求增加一次 Planner 模型调用，延迟和 token 成本会上升。首版以正确性为门禁；调用耗时与 token 只记录。换取的收益是同文不同 session 的正确理解、可审计依赖、失败关闭、可离线测试和更清晰的模块职责。

## 被替代行为

自然语言不再使用 ADR-0002 的关键词快路径，不再注入 `route_hint`，不再使用 RouterAgent 的 `multi-step-plan` skill，也不解析 `[PLAN:...]`。ADR-0004 的“统一理解层”仍有效，但实现主体由 RouterAgent 文本协议调整为独立 PlannerAgent 的类型化输出。

## 实现说明（#44 清理后）

- **遗留 `last_*` session 键的定位**：`last_enum_extract_result`、`last_mapping_data`、`last_threat_data` 仅作为**确定性入口的展示/导出/计数事实**保留——按钮回调（生成 Excel 展示）、`SessionFacts` 的计数字段（`existing_enum_value_count` 等）和会话摘要读取它们；它们**绝不作为规划或步骤输入**（由 `test威胁填充不能读取session旧结果` 等契约测试固化）。ADR-0006 新增的白名单 `session.artifacts.*` 引用来自独立类型化槽位，不会把这些遗留键重新开放为执行输入。
- **Renderer 的“一次汇总 + 一个文件”**：每个 `ExecutionReport` 恰好渲染一次步骤汇总；每个 `config_export` 产物附一个下载文件（契约由 `test成功填充报告输出下载文件` 与 `test三步复合真实链路依次传递账本并产出唯一导出` 固化）。字段映射回填产出的 `_mapped_config.txt` 额外发一条高亮下载消息，是**单步字段映射的 UX 选择**，不违反复合计划不变量（复合计划若无字段映射则天然只有一条汇总）。
- **悬空导入门禁**：`tests/test_chinese_readability.py` 已强制中文 docstring/注释；悬空导入检查待引入 ruff/pyflakes 后补齐（本仓库当前未安装该工具，#44 未收口）。
