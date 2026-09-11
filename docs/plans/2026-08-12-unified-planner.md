# Unified Planner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让所有自然语言业务指令先由独立 PlannerAgent 结合结构化会话事实生成类型化计划，再由确定性 PlanExecutor 校验并执行。

**Architecture:** 新增 `SessionFacts → PlanDecision → PlanExecutor → ExecutionReport` 深层模块。PlannerAgent 只负责理解，专业 Agent 与现有核心函数作为执行适配器；Chainlit 仅适配输入与渲染结果。迁移完成后删除关键词决定路由、文本 PLAN 标记和 handler 内参数猜测。

**Tech Stack:** Python 3.10+、Pydantic、Agno 2.5.17、Chainlit、pytest。

---

### Task 1: 类型化计划契约与会话事实

**Files:**
- Create: `web/planner_models.py`
- Create: `web/session_facts.py`
- Test: `tests/test_planner_contract.py`

1. 先编写失败测试，覆盖 `SessionFacts` 脱敏、步骤 ID 依赖、Fill 显式目标字段和非法计划拒绝。
2. 运行 `python -m pytest -q tests/test_planner_contract.py`，确认因模块不存在而失败。
3. 使用 Pydantic discriminated union 实现 `PlanDecision`、`StepSpec`、`StepResult`、`ExecutionReport`。
4. 实现唯一的 session 状态解释入口 `build_session_facts()`。
5. 再运行该测试，预期全部通过。

### Task 2: 独立 PlannerAgent

**Files:**
- Create: `agent/prompts/planner.md`
- Create: `agent/core/planner.py`
- Test: `tests/test_intent_planner.py`

1. 编写 fake 模型/适配器测试，覆盖单步、复合、澄清、帮助和非法结构拒绝。
2. 运行测试并确认失败。
3. 创建无工具 PlannerAgent，使用 `PlanDecision` output schema；输入只含用户原文、有限历史和 `SessionFacts` JSON。
4. 不注入 route hint，不允许 Planner 调用业务 Agent。
5. 运行测试，预期全部通过。

### Task 3: PlanExecutor 与本次执行账本

**Files:**
- Create: `web/plan_executor.py`
- Create: `web/execution_adapters.py`
- Modify: `web/fill_dispatcher.py`
- Test: `tests/test_plan_executor.py`

1. 编写失败测试：Enum Fill、Enum Extract、Threat 依赖、三步计划、stale session 污染和失败即停止。
2. 实现不依赖 Chainlit 的 PlanExecutor；结构、语义、依赖、执行后验证集中于一个接口。
3. 将 Fill 的领域变更与 UI 消息拆开，返回类型化统计和导出内容。
4. 专业 Agent 与现有 handler 通过适配器返回 `StepResult`，不得读取未声明的旧 `last_*` 结果。
5. 运行定向测试，预期全部通过。

### Task 4: 自然语言统一入口与渲染

**Files:**
- Modify: `web/user_message_handlers.py`
- Modify: `web/response_handler.py`
- Modify: `web/llm_client.py`
- Test: `tests/test_unified_natural_language_entry.py`

1. 编写测试，断言每条自然语言恰好调用 Planner 一次，并且 Planner 返回前任何业务执行器均未调用。
2. 将消息入口缩小为：记录历史、处理确定性清空、构建事实、调用 Planner、执行计划、渲染报告。
3. Planner 失败或要求澄清时不回退 `detect_intent`。
4. 删除 route hint 扫描与 MemberAgent 直达决策。
5. 运行入口回归测试。

### Task 5: 文件和按钮适配

**Files:**
- Modify: `web/file_handlers.py`
- Modify: `web/action_callbacks.py`
- Modify: `web/session_state.py`
- Test: `tests/test_deterministic_command_adapters.py`

1. 测试自然语言和按钮在相同输入下产生相同 Fill 结果。
2. 将按钮/文件事件转换为类型化一步计划并调用 PlanExecutor。
3. 删除会劫持下一条消息的 `enum_fill_mode` / `threat_fill_mode` 业务控制路径。
4. 更新 session 类型，移除字符串/字典混用的 `pending_steps`。
5. 运行相关回归测试。

### Task 6: 文档、可读性与清理

**Files:**
- Create: `docs/adr/0005-independent-planner-agent.md`
- Create: `docs/prd/unified-planner-routing.md`
- Modify: `CONTEXT.md`
- Modify: `docs/architecture/架构概览.md`
- Test: `tests/test_chinese_comments.py`

1. 记录 ADR-0005，并明确自然语言统一入口覆盖 ADR-0002 的直达快路径。
2. 编写 headless PRD，包含实现决策、测试决策和用户故事定位词。
3. 更新领域词汇与架构调用图。
4. 增加本次新增/修改公共模块中文 docstring 与行内注释的静态检查。
5. 删除旧 `[PLAN]`、关键词路由、原文猜参和过期注释。

### Task 7: 验证和 Issue 发布

**Files:**
- Test: `tests/`

1. 运行所有统一 Planner 定向测试。
2. 运行 `python -m pytest -q`，预期全量通过。
3. 使用父 PRD 的精确定位词，将计划拆为 headless tracer-bullet Issues。
4. 按依赖顺序创建父 PRD Issue 和功能 Issues，应用 `enhancement`、`ready-for-agent` 标签。
5. 不关闭或修改 #15、#19、#20 等父 Issue；只在新 Issue 中引用历史背景。
