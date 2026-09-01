# Issue #163 Skip Uploaded Mapped Fields Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 对用户上传的解析规则仅映射 `normalize[].field` 为空的原始字段，完整保留外部已有字段映射。

**Architecture:** `application.session_projection` 在纯上传回退路径中从 `decoded_data` 投影已映射/未映射计数，并仅把未映射 index 放入 #164 建立的 `mappable_fields`。领域 apply 层对非空 `field` 做第二道保护；Executor 与 Adapter 用安全计数区分“无数据”和“全已映射”，后者不调用 LLM 直接成功。`mapped_sub_rules` 继续全量重映射。

**Tech Stack:** Python 3.11、Pydantic、pytest、Application runtime、解析规则领域函数。

---

### Task 1: 建立四类失败回归

**Files:**
- Modify: `tests/test_application_session_projection.py`
- Modify: `tests/test_field_mapping_apply.py`
- Modify: `tests/test_execution_adapters.py`

**Step 1: Write the failing tests**

- 纯上传部分已映射：`available_fields` 保持完整，`mappable_fields` 只包含 `field` 为空的 index，即使其 `mappings` 非空。
- apply 层同时收到新旧映射行时，非空 `field` 条目的 `field/entity/sim/core` 逐字保留，未映射条目正常写入。
- Adapter 的 LLM 输入只含未映射字段，消息包含“新增映射 N 个 / 跳过已映射 M 个”。
- 全已映射配置通过真实 Executor+Adapter 返回 SUCCESS，专业 Agent 零调用。

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_application_session_projection.py tests/test_field_mapping_apply.py tests/test_execution_adapters.py`

Expected: FAIL at candidate filtering, writeback preservation and all-mapped semantics.

### Task 2: 投影上传配置的字段映射状态

**Files:**
- Modify: `contracts/session_facts.py`
- Modify: `application/session_projection.py`
- Test: `tests/test_application_session_projection.py`

**Step 1: Implement the projection**

- 递归统计非系统 normalize 条目的已映射与未映射数量。
- 只以非空 `field` 判定已映射；`mappings` 不参与。
- 纯 `decoded_fields` 回退路径从 `mappable_fields` 剔除已映射 index；真实日志和 `mapped_sub_rules` 贡献保持既有语义。

**Step 2: Run projection tests**

Run: `python -m pytest -q tests/test_application_session_projection.py tests/test_planner_contract.py`

Expected: PASS with stable Planner dictionary and narrowed mapping pool.

### Task 3: 保护写回并实现全已映射成功语义

**Files:**
- Modify: `agent/tools/rule_generator/field_mapping.py`
- Modify: `application/execution.py`
- Modify: `application/adapters/field_mapping.py`
- Test: `tests/test_field_mapping_apply.py`
- Test: `tests/test_execution_adapters.py`

**Step 1: Add the writeback guard**

- `apply_field_mapping_to_config` 在查找新映射前跳过非空 `field` 条目。
- 不改动 `apply_field_mapping_to_sub_rules`，保留全量重映射。

**Step 2: Add the no-op success path and counts**

- Executor 仅对“有上传配置、无未映射条目、有已映射条目”放行空候选池。
- Adapter 在 Runner 之前返回无产物 SUCCESS，提示所有字段已映射。
- 部分已映射时在成功消息中报告新增和跳过数量。

**Step 3: Run focused regressions**

Run: `python -m pytest -q tests/test_field_mapping_apply.py tests/test_execution_adapters.py`

Expected: PASS; uploaded mappings preserved and sub-rule remapping tests remain green.

### Task 4: 同步领域与架构文档

**Files:**
- Modify: `CONTEXT.md`
- Modify: `docs/architecture/代码级设计说明.md`
- Modify: `docs/architecture/领域能力目录.md`
- Regenerate: `docs/source-code-analysis.html`

**Step 1: Record the asymmetric remapping semantics**

- 上传规则保留已有字段映射；会话子规则继续全量重映射。
- 记录 `field` 与 `mappings` 的正交判定。

**Step 2: Regenerate source analysis**

Run: `python scripts/generate_source_code_analysis.py`

Expected: snapshot matches current production files.

### Task 5: 全量验证、提交和合并

**Files:**
- Verify: all issue-scoped changes

**Step 1: Run full verification**

Run: `python -m pytest -q`

Run: `git diff --check`

Expected: all tests pass; only #163 tracked changes are present.

**Step 2: Commit and publish**

Commit: `fix(mapping): preserve uploaded field mappings`

- Push `codex/issue163-skip-uploaded-mapped-fields` to GitHub and GitCode.
- Fast-forward merge into `master`, push both remotes, and close #163 with Chinese evidence.
- Do not create PR/MR.
