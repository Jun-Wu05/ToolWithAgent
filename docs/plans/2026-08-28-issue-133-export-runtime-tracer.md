# Export Runtime Tracer Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the framework-independent execution runtime and session state into Application, then prove the new public seam with an unchanged end-to-end export step.

**Architecture:** Contracts retain immutable types, invariants, and protocols. Application owns `PlanExecutor`, `ExecutionContext`, the in-memory result ledger, the null progress implementation, `SessionState`, shared Adapter helpers, and the export Adapter. Domain-specific preflight rules move behind optional StepAdapter guard interfaces so the execution core depends only on Contracts and the standard library; Web keeps compatibility re-exports and Chainlit wiring.

**Tech Stack:** Python 3.11, dataclasses, Pydantic contracts, asyncio, pytest, AST dependency gates.

---

### Task 1: Characterize the Application execution seam

**Files:**
- Create: `tests/test_application_execution_architecture.py`
- Test: `tests/test_application_execution_architecture.py`

**Step 1: Write failing static dependency tests**

- Assert Application execution, session, and progress core modules do not import `web`, `agent`, `chainlit`, or `agno`.
- Assert legacy `web.plan_executor` and `web.session_state` objects are identical re-exports of Application objects.
- Assert Contracts no longer contains the `NullProgressSink` implementation.

**Step 2: Write a failing export tracer test**

- Construct a real `SessionState`, `SessionFacts`, `ExportStep`, Application `PlanExecutor`, and Application `ExportAdapter`.
- Assert execution succeeds through `ExecutionReport`, emits the same progress sequence, leaves session unchanged, and returns the exact baseline Base64 content and download kind.
- Cover a missing source and stale source to freeze stable `needs_input` error codes.

**Step 3: Run tests and confirm red state**

Run: `python -m pytest tests/test_application_execution_architecture.py -q`

Expected: FAIL because Application runtime modules and compatibility re-exports do not exist.

### Task 2: Move session and progress runtime ownership

**Files:**
- Create: `application/session_state.py`
- Create: `application/progress.py`
- Replace: `web/session_state.py` with compatibility re-exports
- Modify: `contracts/progress.py`
- Modify: production and test imports of `SessionState`, `PrimaryDatasetSnapshot`, and `NullProgressSink`

**Step 1: Move implementations without changing behavior**

- Move `PrimaryDatasetSnapshot` and `SessionState` exactly into Application.
- Move `NullProgressSink` into Application while retaining `ProgressEvent`, enums, and `ProgressSink` protocol in Contracts.
- Keep the old Web session path as an identity-preserving re-export only.

**Step 2: Run session and progress regressions**

Run: `python -m pytest tests/test_session_state_contract.py tests/test_history_store.py tests/test_file_handlers.py tests/test_progress_reporting.py -q`

Expected: PASS with the same lifecycle and event behavior.

### Task 3: Move PlanExecutor and isolate domain guards

**Files:**
- Create: `application/execution.py`
- Replace: `web/plan_executor.py` with compatibility re-exports
- Modify: `web/adapters/agent_ops.py`
- Modify: `web/adapters/skill_ops.py`
- Modify: all production and test imports of `ExecutionContext`, `StepAdapter`, and `PlanExecutor`
- Test: `tests/test_plan_executor.py`

**Step 1: Add optional guard interfaces**

- Define structural plan-level and step-level guard interfaces beside `StepAdapter`.
- Before any step executes, ask registered adapters for plan-level validation; before an adapter executes, ask that adapter for step-level validation.
- Preserve the existing ordered ledger, dependency handling, stable errors, result validation, progress events, and failure closure.

**Step 2: Move concrete validation knowledge**

- Move explicit feature-field validation to the log parse Adapter.
- Move whole-plan event-name validation to the field skill Adapter.
- Keep their messages, normalization behavior, and zero-write-before-rejection invariant unchanged.

**Step 3: Migrate callers and prove identity compatibility**

- New production and tests import the runtime from Application.
- The old Web module only re-exports the same classes/protocols.

**Step 4: Run executor regressions**

Run: `python -m pytest tests/test_plan_executor.py tests/test_progress_reporting.py tests/test_user_message_routing.py tests/test_deterministic_plan.py -q`

Expected: PASS, including feature-field and event-name guards.

### Task 4: Move shared Adapter helpers and the export tracer

**Files:**
- Create: `application/adapters/__init__.py`
- Move: `web/adapters/shared.py` to `application/adapters/shared.py`
- Create: `application/adapters/export.py`
- Replace: `web/adapters/shared.py` with compatibility re-exports
- Modify: `web/adapters/config_ops.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/execution_adapters.py`
- Test: `tests/test_application_execution_architecture.py`
- Test: `tests/test_execution_adapters.py`

**Step 1: Move the shared implementation once**

- Move session access, config artifact encoding, stable result construction, progress publication, retry helpers, and field vocabulary helpers into Application Adapter shared implementation.
- Migrate internal imports; retain the Web path as identity-preserving compatibility only.

**Step 2: Extract ExportAdapter**

- Move the existing export implementation unchanged behind the Application Adapter interface.
- Continue using the existing domain rule generator only inside the Adapter.
- Register the Application ExportAdapter in `create_default_adapters`; do not migrate unrelated business Adapters in this issue.

**Step 3: Run export byte-feature regressions**

Run: `python -m pytest tests/test_application_execution_architecture.py tests/test_execution_adapters.py tests/test_download_kinds.py tests/test_plan_renderer.py -q`

Expected: exact Base64-decoded JSON roots, Chinese encoding, download kinds, filenames, and stable errors remain unchanged.

### Task 5: Update current architecture facts and verify

**Files:**
- Modify: `docs/architecture/架构概览.md`
- Modify: `docs/architecture/统一Planner架构.md`
- Modify: `docs/architecture/chainlit_app模块说明.md`

**Step 1: Document only the completed slice**

- Record Application ownership of execution/session/progress and the export Adapter tracer.
- State explicitly that remaining business Adapters still live under Web and will move in later issues.

**Step 2: Run static and full regression gates**

Run: `rg -n "from web\\.(plan_executor|session_state)|web\\.adapters\\.shared" application web agent tests evaluation --glob "*.py"`

Expected: only compatibility modules or explicit identity tests reference legacy paths.

Run: `python -m pytest`

Expected: all tests pass.

Run: `python -m py_compile application/execution.py application/session_state.py application/progress.py application/adapters/shared.py application/adapters/export.py`

Run: `git diff --check`

Expected: no compile or whitespace errors.

### Task 6: Commit the tracer slice

**Files:**
- Verify: all issue-scoped files

**Step 1: Stage only issue-scoped changes**

- Exclude pre-existing untracked PRD and output artifacts.

**Step 2: Commit**

Commit message: `refactor(application): migrate export execution runtime`
