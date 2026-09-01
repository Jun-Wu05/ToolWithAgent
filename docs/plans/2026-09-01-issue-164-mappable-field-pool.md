# Issue #164 Mappable Field Pool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 分离 Planner 字段点名词典与标准字段映射候选池，阻止已映射的 `normalize[].field` 标准名再次进入 LLM 映射批次。

**Architecture:** `SessionFacts.available_fields` 继续保留原始名与标准名，供 Planner 识别“填充到源IP”等显式目标；新增 `mappable_fields` 仅表示字段映射可消费的原始字段。`PlanExecutor` 的前置校验与 `FieldMappingAdapter` 的批处理输入统一读取新池，保证空池语义和实际执行一致。

**Tech Stack:** Python 3.11、Pydantic、pytest、Chainlit/Application 类型化运行时。

---

### Task 1: 建立双池投影的失败回归

**Files:**
- Modify: `tests/test_application_session_projection.py`
- Modify: `tests/test_execution_adapters.py`
- Modify: `tests/test_plan_executor.py`

**Step 1: Write the failing tests**

- 构造 `index=src_ip, field=源IP` 的 `mapped_sub_rules`，断言 `available_fields` 仍包含 `src_ip` 和 `源IP`，而 `mappable_fields` 只包含 `src_ip`。
- 通过真实 `FieldMappingAdapter` seam 捕获传入批处理的字段，断言不出现 `源IP`。
- 构造“Planner 词典非空但映射池为空”的事实，断言执行器在调用 Adapter 前返回 `needs_input/fields_required`。

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_application_session_projection.py tests/test_execution_adapters.py tests/test_plan_executor.py`

Expected: FAIL because `SessionFacts` 尚无 `mappable_fields`，且 Adapter/执行器仍消费 `available_fields`。

### Task 2: 在 SessionFacts 建立双职责字段池

**Files:**
- Modify: `contracts/session_facts.py`
- Modify: `application/session_projection.py`
- Test: `tests/test_application_session_projection.py`

**Step 1: Implement the minimal projection**

- 新增默认为空 tuple 的 `SessionFacts.mappable_fields`。
- 从同一次会话投影中产生两个有序去重池。
- `available_fields` 维持现有顺序和内容。
- `mappable_fields` 对 `mapped_sub_rules` 只收集 `index`，并剔除与任一非空 `field` 值同名的成员。

**Step 2: Run projection tests**

Run: `python -m pytest -q tests/test_application_session_projection.py tests/test_planner_contract.py`

Expected: PASS; Planner 点名词典的旧断言不变，新映射池断言通过。

### Task 3: 切换映射执行消费者

**Files:**
- Modify: `application/execution.py`
- Modify: `application/adapters/field_mapping.py`
- Modify: `agent/prompts/planner.md`
- Test: `tests/test_execution_adapters.py`
- Test: `tests/test_plan_executor.py`

**Step 1: Switch the consumers**

- `FieldMappingStep` 前置空校验改用 `mappable_fields`。
- `FieldMappingAdapter` 只把 `mappable_fields` 交给 `FieldMappingBatchRunner`。
- Planner prompt 明确 `available_fields` 用于理解点名，`mappable_fields` 决定是否可生成字段映射步骤。

**Step 2: Run focused regressions**

Run: `python -m pytest -q tests/test_execution_adapters.py tests/test_plan_executor.py tests/test_planner_contract.py`

Expected: PASS; 首次映射、再次映射、Planner 显式填充目标均保持正确。

### Task 4: 同步领域与架构文档

**Files:**
- Modify: `CONTEXT.md`
- Modify: `docs/architecture/代码级设计说明.md`
- Modify: `docs/architecture/领域能力目录.md`
- Regenerate: `docs/source-code-analysis.html`

**Step 1: Record the ownership boundary**

- 记录 Planner 词典与映射候选池的不同语义。
- 说明 Session 投影是两个池的唯一构建者，Executor 与 Adapter 不再自行解释。

**Step 2: Regenerate the source snapshot**

Run: `python scripts/generate_source_code_analysis.py`

Expected: generated snapshot matches the current production tree.

### Task 5: 全量验证、提交与合并

**Files:**
- Verify: all issue-scoped changes

**Step 1: Run full verification**

Run: `python -m pytest -q`

Run: `git diff --check`

Expected: all tests pass; no whitespace errors or unrelated tracked changes.

**Step 2: Commit and publish**

Commit: `fix(mapping): separate planner and mappable field pools`

- Push `codex/issue164-mappable-field-pool` to GitHub and GitCode.
- Fast-forward merge the verified branch into `master` and push both remotes.
- Close Issue #164 with Chinese acceptance evidence; do not create PR/MR.
