# Issue #129 Rule Source Fields Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Collect explicit data-source metadata once per primary dataset and use it consistently in entry-rule contents, entry/sub-rule names, exports, and log-derived standard-field mapping.

**Architecture:** Introduce one immutable `RuleSourceFields` contract that owns trimming, required-field validation, and the default `数据源产品(数据源厂商)` composition. Keep rule-shape construction pure inside `agent/tools/rule_generator`, session lifecycle ownership in Application, and Chainlit form/resume behavior in Web. Generator parameters remain optional so callers without source metadata retain their current output exactly.

**Tech Stack:** Python 3, dataclasses, asyncio, Chainlit, Pydantic step contracts, pytest.

---

### Task 1: Define and verify the source-field contract

**Files:**
- Create: `contracts/rule_source.py`
- Create: `tests/test_rule_source_fields.py`

**Steps:**
1. Add failing tests for whitespace normalization, required product/vendor fields, explicit data-source preservation, and blank data-source defaulting to `product(vendor)`.
2. Run the focused tests and verify the missing contract fails.
3. Implement the smallest immutable contract and rerun the tests.

### Task 2: Extend pure rule generation without breaking legacy callers

**Files:**
- Create: `agent/tools/rule_generator/source_fields.py`
- Modify: `agent/tools/rule_generator/core.py`
- Modify: `agent/tools/rule_generator/__init__.py`
- Modify: `tests/test_rule_source_fields.py`

**Steps:**
1. Add failing tests for the entry name, trailing add-fields filter, three normalize entries, three properties, JSON/KV/other sub-rule names, and unchanged legacy output when metadata is absent.
2. Add pure builders for the three entry-rule structures and thread an optional `RuleSourceFields` through all generator APIs.
3. Preserve `additional_fields_filter` and download file naming, and verify focused tests pass.

### Task 3: Own metadata lifecycle in Application

**Files:**
- Modify: `application/session_state.py`
- Modify: `application/file_input.py`
- Modify: `application/request_runtime.py`
- Modify: `tests/test_session_state_contract.py`
- Modify: `tests/test_application_file_input_architecture.py`
- Modify: `tests/test_application_log_parsing_architecture.py`

**Steps:**
1. Add failing tests proving a new primary upload and successful log re-extraction clear both source metadata and a pending source-field step.
2. Add typed session fields and clear them through both typed and dictionary lifecycle seams.
3. Rerun lifecycle tests and confirm unrelated uploaded-config state remains intact.

### Task 4: Gate and propagate metadata at shared Application adapters

**Files:**
- Modify: `application/adapters/export.py`
- Modify: `application/adapters/field_mapping.py`
- Modify: `tests/test_execution_adapters.py`

**Steps:**
1. Add failing adapter tests for entry/sub export gates, mapped-sub-rule guard precedence, generator propagation, log-derived field-mapping gate, and decoded-config-only compatibility.
2. Return stable `needs_input` code `data_source_fields_required`, remember the pending typed step, and pass validated metadata to generators.
3. Ensure decoded-config-only mapping and mapped-sub-rule export stay ungated; rerun adapter tests.

### Task 5: Add the shared Chainlit form and resume the pending step

**Files:**
- Modify: `web/action_callbacks.py`
- Modify: `web/settings_handler.py`
- Modify: `web/plan_renderer.py`
- Modify or create focused Web tests.

**Steps:**
1. Add failing tests for shared form fields, button preflight behavior, renderer fallback for natural-language requests, validation errors, metadata storage, and automatic continuation of a dependency-free pending step.
2. Route source-field submissions before model settings parsing, use collision-safe input IDs, and centralize form construction.
3. Resume the exact pending `ExportStep` or `FieldMappingStep`; for dependency-bearing steps, save metadata and ask the user to retry rather than rebuilding missing dependencies.

### Task 6: Document and verify

**Files:**
- Modify: `CONTEXT.md`
- Regenerate: `docs/source-code-analysis.md`

**Steps:**
1. Document explicit-input semantics, session lifecycle, output structures, naming, and gate boundaries.
2. Regenerate source analysis with `python scripts/generate_source_code_analysis.py`.
3. Run focused suites, `git diff --check`, debug-residue search, then the full pytest suite.
4. Stage only Issue #129 files and create one conventional commit; do not push, merge, or close the issue without explicit user authorization.
