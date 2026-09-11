# Issue #139 Config Runtime Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the Application ownership of field-mapping writeback, remove-mapping, and configuration export while preserving all observable state, errors, messages, filenames, and bytes.

**Architecture:** Keep field-mapping writeback inside the existing deep `FieldMappingAdapter`, where staging and one-time Session commit are already atomic. Move the remaining `RemoveMappingAdapter` implementation into Application, wire production composition directly to it, and retain Web paths only as identity-compatible re-exports. Reuse the existing Application export and configuration-artifact implementation unchanged.

**Tech Stack:** Python 3, Pydantic, pytest, Application StepAdapter contracts.

---

### Task 1: Lock Application ownership and compatibility

**Files:**
- Create: `tests/test_application_config_architecture.py`
- Create: `application/adapters/remove_mapping.py`
- Modify: `application/adapters/__init__.py`
- Modify: `web/adapters/config_ops.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/execution_adapters.py`

**Step 1: Write the failing test**

Assert that the Application remove-mapping module exists without Web or Chainlit imports, default composition registers it directly, all legacy imports are the identical class object, and Web owns no adapter class implementation.

**Step 2: Run test to verify it fails**

Run: `python -X utf8 -m pytest -q tests/test_application_config_architecture.py`
Expected: FAIL because `application.adapters.remove_mapping` does not exist and Web still owns the class.

**Step 3: Write minimal implementation**

Move the current `RemoveMappingAdapter` implementation unchanged into Application, add its lazy export, use it directly in production composition, and reduce Web config operations to re-exports.

**Step 4: Run test to verify it passes**

Run: `python -X utf8 -m pytest -q tests/test_application_config_architecture.py`
Expected: PASS.

### Task 2: Preserve atomic remove-mapping behavior

**Files:**
- Modify: `tests/test_application_config_architecture.py`
- Modify: `application/adapters/remove_mapping.py`

**Step 1: Write one failing behavior test**

Through the public adapter, cover decoded and mapped config refs, standard-name resolution, stale config, ambiguous/missing fields, no mappings, and missing config via the real PlanExecutor. For every failure, assert that Session state is unchanged.

**Step 2: Run the focused test and verify RED**

Run the new test by node id and confirm the intended behavior is not yet protected.

**Step 3: Preserve the existing implementation**

Keep all validation before the single configuration write, deep-copy removal semantics, stable error codes/messages, `changed_count`, and optional field-resolution note.

**Step 4: Run focused and existing tests**

Run: `python -X utf8 -m pytest -q tests/test_application_config_architecture.py tests/test_field_vocabulary.py tests/test_single_intent_execution.py`
Expected: PASS.

### Task 3: Preserve export bytes and user-visible download behavior

**Files:**
- Modify: `tests/test_application_config_architecture.py`
- Verify: `application/adapters/export.py`
- Verify: `web/plan_renderer.py`
- Verify: `web/action_callbacks.py`

**Step 1: Write one byte-contract test**

Assert Base64 decoding is exactly `json.dumps(config, ensure_ascii=False)` for dict and list roots, including insertion order, default spaces, and Chinese text. Assert the remove artifact kind, message, and count.

**Step 2: Run RED, then preserve the existing codec**

Do not introduce a generic codec or change separators, sorting, indentation, encoding, or return type.

**Step 3: Run export and renderer regressions**

Run: `python -X utf8 -m pytest -q tests/test_execution_adapters.py tests/test_plan_renderer.py tests/test_file_handlers.py`
Expected: PASS with existing button names, message counts, filenames, MIME type, and download contents.

### Task 4: Document, verify, commit, and close

**Files:**
- Modify: `CONTEXT.md`

**Step 1: Update current ownership wording**

Record that remove-mapping is now an Application adapter and Web config operations are compatibility exports only.

**Step 2: Run static and full regression gates**

Run: `git diff --check`
Run: `python -X utf8 -m compileall -q application web`
Run: `python -X utf8 -m pytest -q`
Expected: all checks pass.

**Step 3: Commit only Issue #139 files**

Commit message: `refactor(application): migrate config writeback runtime`

**Step 4: Close Issue #139**

Post exact focused/full verification evidence and close the issue. Do not push this branch until the user's next explicit `继续`.
