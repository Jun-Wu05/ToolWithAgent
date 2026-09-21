# Log Knowledge Submission Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让用户仅在日志分类结果满足可靠性门槛时，通过结果区末尾的确定性按钮提交可审核知识；提交具备新鲜度校验、幂等语义和稳定反馈，且不影响已有分类结果。

**Architecture:** 日志解析适配器在成功后构建不含 UI 的类型化提交快照并绑定主数据/分类摘要；按钮只创建 Planner 不可生成的确定性提交步骤，仍由 PlanExecutor 和专用 Application Adapter 执行。Adapter 在写库前重新计算主数据身份并验证快照，随后调用 SQLite 仓储的原子幂等提交 API；Renderer 只根据类型化资格和结果状态追加动作与反馈。

**Tech Stack:** Python 3.11、Pydantic v2、asyncio、SQLite、Chainlit、pytest

---

## Task 1: 冻结提交契约与 Planner 边界

**Files:**
- Modify: `contracts/planner_models.py`
- Modify: `application/execution.py`
- Modify: `web/deterministic_plan.py`
- Test: `tests/test_planner_contract.py`
- Test: `tests/test_plan_executor.py`

1. 写红测试：提交步骤可以走确定性执行入口，但 `PlanDecision`/Planner schema 不能解析或生成该步骤。
2. 增加独立的 `LogKnowledgeSubmitStep` 与提交结果 artifact；保持 Planner 的 `StepSpec` 联合不包含提交步骤。
3. 为执行器增加受类型约束的确定性计划入口，内部复用同一校验、账本、进度和适配器分派，不复制执行逻辑。
4. 跑本任务定向测试至绿。

## Task 2: 构建并生命周期管理提交资格快照

**Files:**
- Modify: `application/session_state.py`
- Modify: `application/file_input.py`
- Modify: `application/adapters/log_parse.py`
- Add: `application/log_knowledge_submission.py`
- Test: `tests/test_log_knowledge_submission.py`
- Test: `tests/test_application_log_parsing_architecture.py`
- Test: `tests/test_application_file_input_architecture.py`

1. 写红测试覆盖：完整成功、至少 3 条有效且可回放真实日志、覆盖率达标、配方可执行和血缘有效时才 eligible；不合格时不产生按钮资格。
2. 定义稳定摘要与规范化规则：区分 automatic/explicit；explicit 身份包含规范化 feature field；摘要只用于新鲜度比较和日志安全观测。
3. 日志解析成功时生成类型化快照，保存有限真实样例、结构/格式/提取配方和主数据摘要；不在普通分类路径写数据库。
4. 新主数据、清空数据或重新解析时使旧快照失效，并覆盖 stale 回归测试。
5. 跑本任务定向测试至绿。

## Task 3: 实现仓储原子幂等提交

**Files:**
- Modify: `agent/tools/log_pattern_store.py`
- Test: `tests/test_log_knowledge_repository.py`
- Test: `tests/test_log_knowledge_submission.py`

1. 写红测试覆盖：首次创建 pending；相同 pending 返回原编号并去重补样本；相同 approved 返回 already-approved；rejected 不阻塞新申请；并发唯一约束竞争可稳定恢复。
2. 在仓储内增加单事务提交 API 和类型化结果，复用现有 identity、样本上限与 SQLite 单一事实源。
3. 将 SQLite 细节异常转换为不含原始日志的稳定仓储错误。
4. 跑本任务定向测试至绿。

## Task 4: 接入提交 Adapter 与新鲜度复核

**Files:**
- Add: `application/adapters/log_knowledge_submit.py`
- Modify: `application/adapters/composition.py`
- Modify: `application/execution.py`
- Test: `tests/test_log_knowledge_submission.py`
- Test: `tests/test_execution_adapters.py`

1. 写红测试覆盖 eligible、stale、repository error、pending duplicate、already-approved；失败不得更改 `log_classification`。
2. Adapter 在任何写入前重新验证当前主数据摘要、分类摘要、样例血缘、覆盖率和配方；过期直接返回稳定结果且零写入。
3. 调用仓储原子 API，并把 created/duplicate/already-approved 映射为类型化 artifact 和用户可读稳定消息。
4. 日志只记录编号、状态、计数和摘要，不记录原始日志或样例内容。
5. 跑本任务定向测试至绿。

## Task 5: 接入 Chainlit 确定性按钮与全部 UI 状态

**Files:**
- Modify: `web/plan_renderer.py`
- Modify: `web/action_callbacks.py`
- Modify: `web/deterministic_plan.py`
- Test: `tests/test_plan_renderer.py`
- Add: `tests/test_log_knowledge_submission_ui.py`

1. 写红测试覆盖 eligible、ineligible、submitting、submitted、duplicate、stale、error 七态。
2. 仅 eligible 分类结果在既有动作列表末尾追加“申请加入知识库”次按钮；ineligible 不显示，且既有上传、分类、规则和下载动作顺序不变。
3. 回调立即禁用/移除当前动作表达 submitting，构造确定性提交步骤并交给统一执行器；成功、重复、已批准、过期和错误均用稳定就地消息反馈。
4. 验证消息与运行日志不泄露原始日志。
5. 跑本任务定向测试至绿。

## Task 6: 文档、全量验证与交付

**Files:**
- Modify: `docs/agents/issue-workflow.md`
- Modify: `docs/source-code-analysis.md`（由脚本生成；若实际生成文件名不同，以脚本输出为准）
- Test: full suite

1. 保留本计划与 pytest worktree 权限教训；不改动主 worktree 的 `CONTEXT.md` 和未跟踪 PRD。
2. 若生产 Python 有改动，运行 `python -X utf8 scripts/generate_source_code_analysis.py`。
3. 运行所有定向测试后，以获批 worktree 写权限执行 `python -X utf8 -m pytest -q --basetemp=.pytest-tmp-203-final`。
4. 检查 `git diff --check`、敏感样例泄露、Planner schema、按钮顺序与仓储状态。
5. 由独立 Tester 回归、Reviewer 检查架构/ADR/安全/兼容性；修复 Major/Blocking 后重跑。
6. 分组提交、推送并创建含 `Closes #203` 和领取协议复核结论的 PR；未经用户明确指示不合并。
