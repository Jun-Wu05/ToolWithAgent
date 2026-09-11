# Field Mapping Batch Runner Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 行为冻结提取 `FieldMappingBatchRunner`，让字段映射适配器不再拥有批处理策略实现。

**Architecture:** 新的 Application 深层模块以一个 `run()` 接口隐藏分批、并发、候选检索、专业 Agent 调用、超时拆批、重试、补查、去重和顺序恢复。Adapter 注入真实或 fake Runner，只保留 StepSpec 翻译、进度接线、领域回填、事件名称标注、产物与 Session 原子提交。

**Tech Stack:** Python 3.11、asyncio、Pydantic、pytest、Agno 专业 Agent 假件

---

### Task 1: 冻结 Runner 接缝

**Files:**
- Create: `tests/test_field_mapping_batch_runner.py`
- Modify: `tests/test_application_field_mapping_architecture.py`

**Step 1: Write failing tests**

覆盖 Runner 无 Session 接口、26 字段两批与顺序、fake Runner 注入、Runner 错误到稳定 StepResult 的转换。

**Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_field_mapping_batch_runner.py tests/test_application_field_mapping_architecture.py`
Expected: FAIL because `application.field_mapping_batch` and `batch_runner` injection do not exist.

### Task 2: 提取深层 Runner 模块

**Files:**
- Create: `application/field_mapping_batch.py`
- Modify: `application/adapters/field_mapping.py`
- Modify: `application/adapters/__init__.py`

**Step 1: Move policy and batch errors**

迁移 `FieldMappingExecutionPolicy` 与 `FieldMappingBatchError`，Adapter 保持同对象重导出。

**Step 2: Move batch implementation unchanged**

把分批、Semaphore、候选检索、专业 Agent 调用、watchdog/Provider 超时、13/12 单层拆批、有限重试、`Retry-After`、漏字段补查、归一化、顺序恢复和任务取消整体迁入 Runner。

**Step 3: Keep Runner session-free**

Adapter 只提取 `original_log_sample`；Runner 不接收 Session，不返回 StepResult，不写业务状态。

### Task 3: 缩减 Adapter 与重定向测试

**Files:**
- Modify: `application/adapters/field_mapping.py`
- Modify: `tests/test_execution_adapters.py`
- Modify: `tests/test_field_mapping_timeout_split.py`

**Step 1: Inject the Runner**

Adapter 默认构造真实 Runner，测试可传 fake Runner；Runner 的批次进度通过 Adapter 绑定的 callback 发布。

**Step 2: Keep post-batch responsibilities in Adapter**

保留 validation、类型化映射、规则应用、事件名称标注、下载产物、消息和成功后的 Session 一次性提交。

**Step 3: Run focused behavior tests**

Run: `pytest -q tests/test_field_mapping_batch_runner.py tests/test_execution_adapters.py tests/test_field_mapping_timeout_split.py tests/test_event_classify.py tests/test_progress_reporting.py`
Expected: PASS with unchanged call counts, progress and atomicity.

### Task 4: 回归与提交

**Files:**
- Modify: `CONTEXT.md` only if the stabilized interface wording changes.

**Step 1: Run static checks and complete suite**

Run: `python -m py_compile application/field_mapping_batch.py application/adapters/field_mapping.py`
Run: `pytest -q`
Expected: all tests pass; only existing third-party warnings may remain.

**Step 2: Review and commit**

确认未修改策略默认值、模型调用次数、进度事件和用户未跟踪文件，然后提交 `refactor(application): extract field mapping batch runner`。
