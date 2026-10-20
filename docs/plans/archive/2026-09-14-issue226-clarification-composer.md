# ClarificationComposer Implementation Plan

**Goal:** Generate safe, concise clarification text from SessionFacts while preserving deterministic choices and exact template fallback behavior.

**Architecture:** Add one async application-level function, `compose_clarification`, that owns safe prompt construction, one bounded model call, and conservative output validation. Renderers opt into composition only when safe `SessionFacts` are supplied; production callers supply those facts, while existing direct renderer calls retain the byte-for-byte template path. `StepResult.choices` carries deterministic NEEDS_INPUT options without parsing user-visible prose.

**Tech Stack:** Python 3.11+, Pydantic contracts, Agno Agent, Chainlit renderer, pytest.

---

### Task 1: Safe composer tracer bullet

**Files:**
- Create: `application/clarification.py`
- Create: `agent/prompts/clarification.md`
- Modify: `agent/prompts/__init__.py`
- Test: `tests/test_clarification.py`

**Step 1: Write the failing test**

Add an async-runner test that calls `compose_clarification("needs_input", facts, "enum_target_field_not_found", ("event_type",), "retry_as_is=1", runner=fake)` and asserts the returned one-sentence explanation is accepted.

**Step 2: Run test to verify it fails**

Run: `python -X utf8 -m pytest -q tests/test_clarification.py::test安全生成文案通过公共接口返回`

Expected: FAIL because `application.clarification` does not exist.

**Step 3: Write minimal implementation**

Implement:

```python
async def compose_clarification(
    kind: str,
    facts: SessionFacts,
    error_code: str | None,
    choices: Sequence[str],
    recovery_summary: str,
    *,
    runner: ClarificationRunner | None = None,
    timeout_seconds: float = 12.0,
) -> str | None:
    ...
```

The function serializes only its typed inputs, invokes either the injected runner or a lazily-created Agno agent once, extracts plain text, and returns `None` for exceptions, timeout, empty text, text over 240 characters, Markdown option lists, or non-whitelisted identifier-like tokens. Add `load_clarification_prompt()` and a prompt that forbids new options and business values.

**Step 4: Run test to verify it passes**

Run the same targeted test; expected PASS.

### Task 2: Safety and fallback boundaries

**Files:**
- Modify: `tests/test_clarification.py`
- Modify: `application/clarification.py`

**Step 1: Add one failing behavior test at a time**

Cover captured runner input excluding a sensitive raw sample, empty output, exception, timeout, overlong output, added Markdown choices, and a quoted/ASCII identifier not present in deterministic choices or safe fact field names.

**Step 2: Make each test green before adding the next**

Keep validation private to the module; the only public application interface remains `compose_clarification`.

### Task 3: Preserve deterministic NEEDS_INPUT choices

**Files:**
- Modify: `contracts/planner_models.py`
- Modify: `application/execution_policy.py`
- Test: `tests/test_plan_executor.py`

**Step 1: Write a failing enum-target test**

Assert `enum_target_field_not_found` returns `StepResult.choices` exactly equal to the sorted known fields.

**Step 2: Implement the contract**

Add `choices: tuple[str, ...] = ()` to `StepResult`; let `_needs_input` receive deterministic choices and populate them for enum-target and explicit log-feature guards.

**Step 3: Run focused policy tests**

Run: `python -X utf8 -m pytest -q tests/test_plan_executor.py`

Expected: PASS.

### Task 4: Clarification decision rendering

**Files:**
- Modify: `web/plan_renderer.py`
- Test: `tests/test_plan_renderer.py`

**Step 1: Write a failing renderer test**

Pass safe facts and a fake runner to `render_decision`; assert generated explanation replaces only `decision.question` and the rendered choices remain byte-for-byte identical.

**Step 2: Implement minimal opt-in composition**

Extend `render_decision` with keyword-only `session_facts` and `clarification_runner`. When facts are absent, do not call the composer and preserve the old output exactly.

**Step 3: Add fallback test**

An exception/empty fake response must produce the exact previous message.

### Task 5: NEEDS_INPUT report rendering and production wiring

**Files:**
- Modify: `web/plan_renderer.py`
- Modify: `web/user_message_handlers.py`
- Modify: `web/deterministic_plan.py`
- Test: `tests/test_plan_renderer.py`
- Test: `tests/test_user_message_routing.py`
- Test: `tests/test_deterministic_plan.py`

**Step 1: Write a failing report test**

For an enum target miss, assert generated text names the safe suggested field, the separately rendered choices equal `StepResult.choices`, and the original missing target/sample value never reaches the runner prompt.

**Step 2: Implement one-call report composition**

Before building the summary, compose at most the first NEEDS_INPUT result. Derive recovery summary only from `recovered` counts. Append deterministic choices after generated explanation; on failure pass no replacement so `build_execution_report_content` remains byte-for-byte compatible.

**Step 3: Wire production callers**

Supply `build_session_facts(user_session)` from natural-language and deterministic execution paths. Update routing test doubles to accept the new keyword arguments.

### Task 6: Verification and delivery

**Files:**
- Regenerate: `docs/source-code-analysis.html`

**Step 1: Regenerate architecture snapshot**

Run the repository's source-analysis generator because production Python files changed.

**Step 2: Run focused tests**

Run composer, policy, renderer, routing, deterministic-plan, request-runtime, architecture, and recovery test modules.

**Step 3: Run full suite**

Run: `python -X utf8 -m pytest -q`

Expected: all tests pass.

**Step 4: Review and commit**

Review `git diff`, `git diff --check`, and staging scope. Create one conventional commit for Issue #226, push the short-lived branch, and open a PR containing `Closes #226`, dependency evidence, TDD evidence, and the functional-issue acceptance mapping. Do not merge without explicit user authorization.
