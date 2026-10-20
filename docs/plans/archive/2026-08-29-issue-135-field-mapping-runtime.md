# Field Mapping Runtime Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将字段映射与事件名称标注的完整垂直链路原样迁入 Application，并保持调用策略、产物与 Session 原子提交不变。

**Architecture:** Application 获得字段来源、批次输入、字段映射结果解析和 `FieldMappingAdapter` 的实现所有权；Application Adapter 可依赖专业 Agent 与领域函数，但不得依赖 Web。Web 旧路径只重导出 Application 中的同一个对象，`create_default_adapters` 仍是唯一生产组合接缝。

**Tech Stack:** Python 3.11、asyncio、Pydantic、pytest、Agno 专业 Agent 假件

---

### Task 1: 冻结 Application 接缝

**Files:**
- Create: `tests/test_application_field_mapping_architecture.py`

**Step 1: Write the failing test**

增加静态依赖、同对象兼容导出、默认组合和字段映射 tracer 契约测试。

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_application_field_mapping_architecture.py`
Expected: FAIL because `application.adapters.field_mapping` does not exist.

### Task 2: 迁移字段映射支撑模块

**Files:**
- Create: `application/field_source.py`
- Create: `application/field_mapping_input.py`
- Modify: `application/parsing.py`
- Modify: `application/session_projection.py`
- Modify: `web/field_source.py`
- Modify: `web/input_builder.py`
- Modify: `web/parsers.py`

**Step 1: Move the implementations**

将字段来源、批次输入和 `parse_json_mapping_result()` 原样迁入 Application；只改变导入归属。

**Step 2: Preserve legacy identity**

旧 Web 路径重导出同一个函数对象，新生产调用切到 Application。

**Step 3: Run focused tests**

Run: `pytest -q tests/test_application_field_mapping_architecture.py tests/test_field_source_fallback.py tests/test_parsers.py tests/test_log_redaction.py`
Expected: PASS.

### Task 3: 原样迁移字段映射适配器

**Files:**
- Create: `application/adapters/field_mapping.py`
- Modify: `application/adapters/__init__.py`
- Modify: `web/adapters/field_mapping.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/adapters/agent_ops.py`
- Modify: `web/execution_adapters.py`
- Modify: `tests/test_chinese_readability.py`

**Step 1: Move the implementation unchanged**

保留 `FieldMappingExecutionPolicy`、`FieldMappingBatchError` 和 `FieldMappingAdapter` 的批大小、并发、超时拆批、重试、`Retry-After`、补查、顺序、事件名称标注和原子写回实现。

**Step 2: Rewire composition and compatibility exports**

唯一生产组合入口直接注册 Application 适配器；旧 Web 模块只做同对象重导出。

**Step 3: Run behavior tests**

Run: `pytest -q tests/test_application_field_mapping_architecture.py tests/test_execution_adapters.py tests/test_field_mapping_timeout_split.py tests/test_event_classify.py tests/test_rule_targeting.py`
Expected: PASS with unchanged call counts and session behavior.

### Task 4: 回归与提交

**Files:**
- Modify: `CONTEXT.md`

**Step 1: Update current architecture wording**

只更新当前事实源中字段映射适配器的物理归属；不改历史文档。

**Step 2: Run the complete suite**

Run: `pytest -q`
Expected: all tests pass; only existing third-party warnings may remain.

**Step 3: Review and commit**

检查旧路径只剩兼容性测试/重导出，确认未混入用户未跟踪文件，然后提交 `refactor(application): migrate field mapping runtime`。
