# Issue #166 Sub-rule Export Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent exporting an unmapped “whiteboard” sub-rule configuration after mapped sub-rules exist, and invalidate stale mapping-derived state when log types are extracted again.

**Architecture:** Keep export validation in `ExportAdapter`, the common typed seam used by both deterministic buttons and Planner-generated export steps. Add one Application session lifecycle function that atomically commits a new `log_classification`, clears only mapping-derived state, and removes enum bookkeeping bound to `session.mapped_sub_rules` while preserving independent uploaded-config state.

**Tech Stack:** Python 3, asyncio, Pydantic contracts, pytest.

---

### Task 1: Guard whiteboard sub-rule export

**Files:**
- Modify: `tests/test_execution_adapters.py`
- Modify: `application/adapters/export.py`

**Step 1: Write the failing test**

Add an adapter-level test that executes an `ExportStep` with `source_ref="session.log_classification.sub_rules"` while `mapped_sub_rules` is non-empty. Assert `needs_input`, stable error code `mapped_sub_rules_present`, an explicit “生成映射后子规则” instruction, no artifact, and no call to rule generation.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_execution_adapters.py -k "白板子规则"`

Expected: FAIL because the current adapter exports `unmappedconfig_subrules`.

**Step 3: Write minimal implementation**

Before regenerating only the sub-rule source, check `mapped_sub_rules`. Return `_needs_input(...)` with the stable code and explicit full-version export route. Do not apply the gate to entry rules or `session.mapped_sub_rules`.

**Step 4: Run focused regression tests**

Run: `python -m pytest -q tests/test_execution_adapters.py -k "规则导出 or 白板子规则"`

Expected: PASS.

### Task 2: Commit log classification atomically

**Files:**
- Modify: `application/session_state.py`
- Modify: `application/adapters/log_parse.py`
- Modify: `tests/test_application_log_parsing_architecture.py`

**Step 1: Write the failing test**

Add a public-adapter regression test with an existing mapped configuration and mapping result tables. Include enum contribution, stale, and pending-refill entries for both `session.mapped_sub_rules` and `session.decoded_config`. After successful re-extraction, assert mapping-derived values are cleared, mapped-sub-rule enum bookkeeping is removed, decoded-config bookkeeping is preserved, and the result message explicitly warns that mapping/event annotation/manual adjustments were cleared.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_application_log_parsing_architecture.py -k "重提取"`

Expected: FAIL because the current adapter only overwrites `log_classification`.

**Step 3: Write minimal implementation**

Add `commit_log_classification(session, classification) -> bool` to the Application session lifecycle. It clears `mapped_sub_rules`, `sub_rule_mapping_results`, `batch_mapping_results`, `last_mapping_data`, legacy mapping exports, and only the enum bookkeeping entry bound to `session.mapped_sub_rules`, then stores the new classification. Return whether meaningful mapping-derived state existed so `LogParseAdapter` can append the warning only when data was actually invalidated.

**Step 4: Prove the gate releases after re-extraction**

Extend the test through `ExportAdapter` or `PlanExecutor` and assert the whiteboard export succeeds after state invalidation. Assert `session.mapped_sub_rules` export no longer returns stale content.

**Step 5: Run focused tests**

Run: `python -m pytest -q tests/test_application_log_parsing_architecture.py tests/test_execution_adapters.py`

Expected: PASS.

### Task 3: Document and verify the domain behavior

**Files:**
- Modify: `CONTEXT.md`

**Step 1: Update the domain SSOT**

Document that whiteboard sub-rule export is blocked while mapped sub-rules exist, mapped export is the explicit route, and successful log-type re-extraction invalidates mapping/event annotation/manual-adjustment derivatives with a visible warning.

**Step 2: Run architecture and full regression suites**

Run: `python -m pytest -q tests/test_application_log_parsing_architecture.py tests/test_application_execution_architecture.py tests/test_execution_adapters.py tests/test_session_state_contract.py`

Run: `python -m pytest -q`

Expected: PASS, allowing only pre-existing warnings.

### Task 4: Review and deliver

**Files:**
- Review only the tracked files changed for Issue #166; preserve all pre-existing untracked PRD and `outputs/` files.

**Step 1: Inspect the diff and debug residue**

Run: `git diff --check`

Run: `rg -n "\[DEBUG-" application tests`

Expected: no whitespace errors and no temporary probes.

**Step 2: Commit the logical change**

Stage only Issue #166 files and create a conventional commit describing the export guard and re-extraction invalidation.

**Step 3: Publish and close**

Push the branch to both configured remotes. After verification, fast-forward `master` only as already authorized by the active project workflow, push both remotes, and close Issue #166 with a Chinese summary and commit reference.
