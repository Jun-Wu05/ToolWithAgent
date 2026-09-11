# Issue #143 Web Entry Cutover Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route every Chainlit business entry through public Application modules and delete only migration compatibility paths proven to have zero references.

**Architecture:** Deepen three Application modules: request runtime owns Planner-to-Executor orchestration, execution policy owns domain preflight composition, and model runtime owns per-session Team configuration. Existing Application file/session modules remain the upload and startup seams. Web retains only Chainlit registration, input adaptation, progress lifecycle and rendering.

**Tech Stack:** Python 3, Chainlit adapters, Pydantic contracts, pytest, AST dependency gates.

---

### Task 1: Freeze Chainlit registration and observable entry behavior

**Files:**
- Create: `tests/test_web_entry_architecture.py`
- Modify: `web/chainlit_app.py`
- Modify: `web/message_router.py`

1. Write one failing test that statically records exactly one chat-start, settings-update and message registration plus the current Action callback names.
2. Run the test and confirm the duplicate message registration fails.
3. Remove handler-level duplicate registration, leaving the Chainlit composition root as lifecycle owner.
4. Run the registration and existing user-message/action-related tests.

### Task 2: Deepen the Application request and execution-policy modules

**Files:**
- Create: `application/execution_policy.py`
- Create: `application/request_runtime.py`
- Modify: `web/user_message_handlers.py`
- Modify: `web/deterministic_plan.py`
- Modify: `tests/test_user_message_routing.py`
- Modify: `tests/test_deterministic_plan.py`
- Modify: `tests/test_plan_executor.py`

1. Write a failing public-interface test: one natural-language request calls Planner once, executes only an execute decision, reuses the same safe SessionFacts and progress sink, and returns a typed decision/report without rendering.
2. Move the existing domain preflight policy unchanged into Application and implement the minimal request runtime.
3. Make Web own only progress lifecycle and rendering; make deterministic Action plans use the same Application execution function.
4. Run the request, deterministic plan, execution-policy, progress and renderer suites.

### Task 3: Deepen the Application model-session module

**Files:**
- Create: `application/model_runtime.py`
- Modify: `web/settings_handler.py`
- Modify: `web/message_router.py`
- Modify: `web/start_handler.py`
- Modify: `tests/test_settings_provider.py`
- Modify: `tests/test_web_entry_architecture.py`

1. Write a failing test for reset/apply/lazy Team initialization through a public Application interface while preserving environment-key resolution and failure behavior.
2. Implement reset, apply and ensure-Team operations around the existing provider registry and Team cache.
3. Switch settings and message adapters to that interface; keep widgets, connection probes and user messages in Web.
4. Expose session creation/cache initialization through Application startup functions without moving logging-bridge or Chainlit rendering state.
5. Run provider, startup and message tests.

### Task 4: Switch upload and display-only Action helpers to public Application modules

**Files:**
- Modify: `web/file_handlers.py`
- Modify: `web/file_handler.py`
- Modify: `web/action_callbacks.py`
- Create or modify: focused Application query/helper modules only when business logic currently calls Agent directly
- Modify: `tests/test_file_handlers.py`
- Modify: Action-related tests

1. Add a failing gate that upload decoding/commit and Action business operations import public Application names directly.
2. Remove decode/enum-commit compatibility aliases and direct Agent business imports from Web entry modules.
3. Preserve all Chainlit messages, tables, actions and attachment bytes.
4. Run file lifecycle, field mapping, enum, referenceable artifact and renderer tests.

### Task 5: Delete only zero-reference migration compatibility paths

**Files:**
- Delete after proof: pure Web runtime/Adapter compatibility modules and the old Core Prompt compatibility module
- Modify: partial compatibility modules to retain only their non-migration implementation
- Modify: tests that still import legacy paths
- Modify: current architecture documentation

1. Add a failing AST/reference gate listing all migration compatibility imports and definitions that must reach zero.
2. Migrate tests to Application public interfaces; replace old identity assertions with absence and dependency-direction assertions.
3. Remove pure re-export files only after production, dynamic, package and test searches return zero.
4. Retain the historical Base64 encoder, Web constants and both logging-bridge state locations unchanged except for removing a migrated re-export name where required.
5. Run cold imports, compileall, diff checks and the full pytest suite.

### Task 6: Deliver

1. Review exact staged diff and confirm user-owned untracked files are untouched.
2. Commit one logical conventional refactor commit.
3. Post test and zero-reference evidence to #143 and close it.
4. Leave the branch unpushed until the next explicit continuation.
