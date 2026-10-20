# Issue #142 Prompt and Adapter Composition Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the Prompt package the sole owner of every current Prompt loader and make Application the sole owner of production Adapter composition without changing business behavior.

**Architecture:** Add the two missing package-local loaders for Planner and event classification, then make their consumers import those public functions. Define `create_default_adapters` once in an Application composition module; Web compatibility modules re-export that exact object while production Web callers import Application directly. Static architecture tests enforce ownership, dependency direction, registry completeness, and legacy identity.

**Tech Stack:** Python 3, Pydantic contracts, pytest, AST-based dependency tests.

---

### Task 1: Freeze Prompt ownership in tests

**Files:**
- Create: `tests/test_prompt_package_architecture.py`
- Modify: `agent/prompts/__init__.py`
- Modify: `agent/core/planner.py`
- Modify: `agent/shared/event_classify.py`

1. Add a failing test proving the Prompt package exposes loaders for all 12 Prompt assets, preserves exact content, no-cache behavior and each historical missing-file policy.
2. Add a failing test proving Planner and event classification consume public Prompt-package loaders and legacy log loaders remain identical re-exports.
3. Implement `load_planner_prompt()` and `load_event_classify_prompt()` in the Prompt package, with explicit `__all__`.
4. Replace direct resource reads in Planner and event classification without changing call timing or Prompt concatenation.
5. Run the Prompt architecture tests and related Planner/event tests.

### Task 2: Move unique Adapter composition into Application

**Files:**
- Create: `application/adapters/composition.py`
- Modify: `application/adapters/__init__.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/execution_adapters.py`
- Modify: `web/user_message_handlers.py`
- Modify: `web/deterministic_plan.py`
- Create: `tests/test_application_composition_architecture.py`

1. Add a failing test proving only one production definition exists, its registry exactly covers all 12 StepSpec types, and field-skill operations share one Adapter instance.
2. Add a failing compatibility test proving both Web entry points re-export the Application function object.
3. Add a failing static test proving production Web consumers import the Application composition seam directly.
4. Implement the Application composition module and lazy public export.
5. Reduce Web composition modules to compatibility re-exports and migrate production callers.
6. Run composition, execution, and business Adapter tests.

### Task 3: Add package dependency gates

**Files:**
- Modify: `tests/test_application_composition_architecture.py`

1. Add AST gates: Contracts cannot import Agent/Application/Skills/Web/Chainlit; Application cannot import Web/Chainlit; Agent and Skills cannot import Web/Chainlit.
2. Retain the stronger existing Application-core gate and avoid broad private-import cleanup outside this issue.
3. Run architecture tests and cold-import checks.

### Task 4: Verify and deliver

1. Run focused Prompt, Planner, event, composition, execution, and Adapter suites.
2. Run the full pytest suite and compile changed modules.
3. Inspect exact diff and repository status; stage only #142 tracked changes.
4. Commit with a conventional architecture-refactor message.
5. Post evidence to #142 and close it; leave the branch unpushed until the next explicit continuation.
