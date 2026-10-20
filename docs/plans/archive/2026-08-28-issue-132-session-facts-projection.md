# Session Facts Projection Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep `SessionFacts` as a pure Contracts data model while moving session reads and safe fact projection into an Application-owned module without changing planner-visible facts or session artifact lifecycle behavior.

**Architecture:** `contracts.session_facts` will contain only immutable Pydantic fact types. `application.session_projection` will be the single implementation that reads `SessionState`-like objects, collects fields and annotations, resolves configuration targets, validates typed artifact slots, and returns `SessionFacts`. Production and test callers will import the Application entry point directly; no reverse dependency from Contracts will remain.

**Tech Stack:** Python 3.11, Pydantic, pytest, static AST/import scans.

---

### Task 1: Add the dependency and projection characterization gates

**Files:**
- Create: `tests/test_application_session_projection.py`
- Test: `tests/test_application_session_projection.py`

**Step 1: Write the failing tests**

- Assert every Python file under `contracts/` has no imports rooted at `web`, `application`, `chainlit`, or `agent`.
- Build facts through `application.session_projection.build_session_facts` from the same representative session used by the existing planner contract and artifact tests.
- Assert the projection contains the same fields, config references, event annotations, counts, and safe referenceable artifact catalog.
- Assert serialized facts do not contain sensitive artifact values, local paths, or API keys.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_application_session_projection.py -q`

Expected: FAIL because `application.session_projection` does not yet exist and Contracts still imports Agent/Web implementations.

### Task 2: Extract the Application projection implementation

**Files:**
- Create: `application/__init__.py`
- Create: `application/session_projection.py`
- Modify: `contracts/session_facts.py`
- Modify: `contracts/__init__.py`
- Test: `tests/test_application_session_projection.py`

**Step 1: Move the implementation**

- Leave only `EventAnnotationFact` and `SessionFacts` in `contracts.session_facts`.
- Move session compatibility reads, field collection, counts, rule names, event annotations, target bindings, typed artifact validation, and `build_session_facts` to `application.session_projection`.
- Preserve ordering, validation, redaction, and invalid-slot behavior byte-for-byte where practical.

**Step 2: Run focused tests**

Run: `python -m pytest tests/test_application_session_projection.py tests/test_planner_contract.py tests/test_referenceable_session_artifacts.py -q`

Expected: projection and dependency gates pass.

### Task 3: Migrate all repository callers to the Application seam

**Files:**
- Modify: `web/user_message_handlers.py`
- Modify: `web/deterministic_plan.py`
- Modify: `web/action_callbacks.py`
- Modify: every test currently importing `build_session_facts` from `contracts.session_facts`

**Step 1: Replace imports**

- Import `build_session_facts` only from `application.session_projection`.
- Keep direct imports of the `SessionFacts` type from Contracts.
- Verify no production or test reference remains to the removed Contracts builder.

**Step 2: Run migration checks**

Run: `rg -n "from contracts\.session_facts import build_session_facts" application web agent tests`

Expected: no matches.

Run: `python -m pytest tests/test_user_message_routing.py tests/test_deterministic_plan.py tests/test_execution_adapters.py tests/test_field_skill_ops.py tests/test_field_skill_extensions.py -q`

Expected: PASS with unchanged behavior.

### Task 4: Verify session lifecycle and architectural documentation

**Files:**
- Modify: `docs/architecture/架构概览.md`
- Modify: `docs/architecture/统一Planner架构.md`
- Test: `tests/test_file_handlers.py`
- Test: `tests/test_session_state_contract.py`
- Test: `tests/test_referenceable_session_artifacts.py`

**Step 1: Update current architecture facts**

- Document Contracts as pure immutable types and Application as the owner of session projection.
- Keep PlanExecutor, SessionState, adapters, and later migration targets at their current paths; do not claim the parent architecture migration is complete.

**Step 2: Run lifecycle regressions**

Run: `python -m pytest tests/test_file_handlers.py tests/test_session_state_contract.py tests/test_referenceable_session_artifacts.py -q`

Expected: primary dataset replacement, invalid upload preservation, typed artifact invalidation, and safe catalog behavior all pass unchanged.

### Task 5: Full verification and handoff

**Files:**
- Verify: all changed files

**Step 1: Run full tests**

Run: `python -m pytest`

Expected: all tests pass.

**Step 2: Run repository checks**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors; only issue-scoped tracked changes plus pre-existing user-owned untracked files.

**Step 3: Commit the vertical slice**

Commit message: `refactor(application): extract session facts projection`
