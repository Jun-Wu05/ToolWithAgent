# Issue #140 Field Skill Runtime Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use tdd to implement this plan task-by-task.

**Goal:** Move the typed field-adjustment Skills runtime into Application while preserving its declarative registry, script SSOT, Session commits, artifacts, errors, and model-call policy.

**Architecture:** Application owns one `FieldSkillAdapter` and the registry-to-script loader. Web retains an identity-preserving compatibility re-export and uses the Application object in the existing production composition root. The five scripts under `skills/` remain unchanged.

**Tech Stack:** Python, Pydantic planner contracts, pytest, importlib.

---

### Task 1: Freeze Application ownership

Write a failing architecture test for the new module, dependency direction, compatibility identity, and shared production adapter instance; then move the implementation and make the test pass.

### Task 2: Freeze resource loading

Add tests for exact registry entries, loading from a non-repository working directory, and a cold Python import. Preserve package lazy exports and avoid eager cycles.

### Task 3: Freeze runtime semantics

Reuse the existing field operation suites to preserve inputs, outputs, stable errors, targeting, binding, Base64 artifacts, and atomic Session updates. Add a deterministic execution assertion that no Planner or professional Agent is introduced.

### Task 4: Verify and deliver

Run focused tests, full pytest, compileall, and diff checks. Commit exact files, post evidence to #140, and close it without pushing this branch until the next explicit continuation.
