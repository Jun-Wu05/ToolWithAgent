# Issue #144 Documentation and Zero-Regression Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the maintained documentation and source-analysis snapshot describe the final Application runtime, then prove the migration preserved behavior.

**Architecture:** Treat the checked-out Python source as the physical-architecture source of truth, Contracts and ADRs as the interface source of truth, and Issue #144 plus PRD #130 as the behavior source of truth. Add a reproducible, standard-library-only source-analysis generator so the HTML inventory, line counts, imports, callers, semantic layers, responsibilities, and reading order can be regenerated and verified instead of hand-edited.

**Tech Stack:** Python 3, AST, pathlib, pytest, Markdown, standalone HTML/CSS/JavaScript, GitHub CLI, Chainlit browser acceptance tooling.

---

## Preconditions and PRD preflight

- Issue #144 is `ready-for-agent` and its Agent Brief is published.
- Dependency #143 is closed; commit `3907fbd` is in this stacked baseline and is pushed to `origin`.
- PRD implementation summary: maintained documentation must follow the final code, record Application ownership and one-way dependencies in a new ADR, preserve historical documents, freeze user-observable behavior, and remain strictly serial.
- PRD test summary: scan maintained docs for obsolete production paths, verify the HTML inventory against the repository, then run the full offline suite, Planner semantic evaluation, real Chainlit browser acceptance, and security/observability checks.
- User-story summary: US-4/US-5 preserve all upload, planning, business-operation, and download behavior; US-6 preserves model call stages and counts; US-11 protects public seams and dependency direction; US-15 gives maintainers accurate navigation and architecture facts.

## Architecture candidates

1. **Hand-edit the existing ignored HTML.** Small initial diff, but line counts, imports, callers, and file inventory will drift again. Rejected because the acceptance criterion explicitly requires regeneration and item-by-item verification.
2. **Add a reproducible generator and commit its generated HTML.** One deterministic command derives inventory facts from source and keeps editorial layer descriptions explicit. Chosen because it separates measured facts from architecture narrative and makes regression tests meaningful.
3. **Replace the HTML with Markdown only.** Easier maintenance but fails the required `docs/source-code-analysis.html` deliverable and removes the interactive inventory. Rejected.

### Task 1: Establish documentation consistency RED gates

**Files:**
- Create: `tests/test_documentation_architecture.py`
- Read: `README.md`
- Read: `CONTEXT.md`
- Read: `docs/architecture/架构概览.md`
- Read: `docs/architecture/代码级设计说明.md`
- Read: `docs/architecture/chainlit_app模块说明.md`
- Read: `docs/architecture/统一Planner架构.md`
- Read: `docs/architecture/测试场景手册.md`

**Step 1: Write the failing maintained-document test**

Assert that maintained docs do not present deleted Web runtime modules or the old Core Prompt shim as current production paths, and that they name the Application request, execution, session, history, model, field, file, and adapter boundaries.

**Step 2: Run the test to verify RED**

Run: `python -m pytest -q tests/test_documentation_architecture.py -k maintained_docs`

Expected: FAIL on current references such as `web/plan_executor.py`, `web/session_state.py`, `web/history_store.py`, `web/adapters/`, `web/execution_adapters.py`, and `agent/core/prompts.py`.

**Step 3: Keep the test public and data-driven**

The test reads committed documentation and production paths only; it must not assert prose formatting or private implementation symbols.

### Task 2: Record the final Application architecture

**Files:**
- Create: `docs/adr/0009-application-runtime-ownership.md`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `docs/architecture/架构概览.md`
- Modify: `docs/architecture/代码级设计说明.md`
- Modify: `docs/architecture/chainlit_app模块说明.md`
- Modify: `docs/architecture/统一Planner架构.md`
- Modify: `docs/architecture/测试场景手册.md`
- Modify: `CHANGELOG.md`

**Step 1: Update one maintained document slice at a time**

Use the final source tree and public imports to describe `web → application → contracts`, with Application adapters connecting to Agent/domain implementations. Mark ADR-0001 through ADR-0004 path details as historical where referenced; do not rewrite those ADRs.

**Step 2: Add ADR-0009**

Record Application ownership, core/adapters dependency boundaries, temporary compatibility deletion, frozen behavior, and consequences. State which physical-path details in older ADRs are superseded without changing their historical text.

**Step 3: Update navigation and changelog**

Add ADR-0009 and the source-analysis map to README navigation. Add one `Changed` entry for the completed runtime extraction and documentation synchronization.

**Step 4: Run the focused test to verify GREEN**

Run: `python -m pytest -q tests/test_documentation_architecture.py -k maintained_docs`

Expected: PASS.

### Task 3: Make source analysis reproducible

**Files:**
- Create: `scripts/generate_source_code_analysis.py`
- Modify: `.gitignore`
- Regenerate: `docs/source-code-analysis.html`
- Modify: `tests/test_documentation_architecture.py`

**Step 1: Write the failing snapshot verification test**

Verify that the committed HTML metadata matches the current production file set and physical line counts; every listed import/caller path exists; Application is a semantic layer; deleted Web compatibility paths are absent; and no absolute local path or secret value is embedded.

**Step 2: Run the test to verify RED**

Run: `python -m pytest -q tests/test_documentation_architecture.py -k source_analysis`

Expected: FAIL because the current ignored snapshot was generated at `beb04d3` and still lists deleted Web runtime files.

**Step 3: Implement the standard-library generator**

Scan `application/**/*.py`, `contracts/**/*.py`, `web/**/*.py`, `agent/**/*.py`, and `skills/**/scripts/**/*.py`. Derive physical line counts, public classes/functions, local imports, reverse callers, top-level subsystem, and explicit semantic-layer assignments. Render one self-contained HTML document with architecture layers, flows, inventory, search/filter/sort, and generated metadata.

**Step 4: Regenerate and verify GREEN**

Run: `python scripts/generate_source_code_analysis.py`

Run: `python -m pytest -q tests/test_documentation_architecture.py -k source_analysis`

Expected: PASS, with exact file and line totals matching the checkout.

**Step 5: Visually inspect the generated page**

Open the local HTML, exercise search/filter/sort and layer/file selection at desktop and narrow widths, and confirm no clipping, missing content, stale paths, or JavaScript errors.

### Task 4: Protect historical boundaries and links

**Files:**
- Modify: `tests/test_documentation_architecture.py`
- Modify only maintained documents listed in Task 2 if the gate finds defects.

**Step 1: Write the failing boundary/link test**

Check internal links in maintained docs, require current-doc references to dated/obsolete material to label it historical, and ensure no historical PRD or ADR file was modified by this issue except the new ADR.

**Step 2: Run RED, apply the smallest corrections, and rerun GREEN**

Run: `python -m pytest -q tests/test_documentation_architecture.py -k 'links or historical'`

Expected: PASS after maintained-link corrections; historical source files remain untouched.

### Task 5: Run complete zero-regression gates

**Files:**
- No production code changes expected.
- Store runtime evidence only in ignored `outputs/` paths; do not stage user-owned output files.

**Step 1: Run focused architecture/documentation tests**

Run: `python -m pytest -q tests/test_documentation_architecture.py tests/test_application_request_runtime.py tests/test_application_model_runtime.py tests/test_web_entry_architecture.py`

Expected: PASS.

**Step 2: Run the complete offline suite**

Run: `python -m pytest -q`

Expected: all tests pass; compare count with the #143 baseline of 444 plus the new documentation gates.

**Step 3: Run Planner semantic evaluation**

Run: `python evaluation/planner_semantic_eval.py --runs 3 --output outputs/issue144-planner-eval.jsonl`

Expected: zero failures; schema, plans, safety behavior, call stages, latency, and token observations recorded without secrets.

**Step 4: Run real Chainlit browser acceptance**

Use the repository browser-acceptance skill against the real Chainlit UI. Cover model settings, Excel upload, log type extraction, field mapping, enum extraction, threat mapping, fill, field adjustment, export, Base64 direct operation, failure clarification, and cross-turn artifact reuse. Compare observable behavior and downloads with the frozen baseline.

**Step 5: Verify repository scope**

Run exact stale-reference scans, `git diff --check`, documentation tests, and `git status --short`. Confirm user-owned `docs/prd/application-runtime-extraction.md` and existing `outputs/` files remain unstaged.

### Task 6: Commit and close the issue

**Files:**
- Stage only the files created or modified by Tasks 1–4.

**Step 1: Review the complete diff**

Confirm no business code, prompt, UI behavior, historical ADR/PRD, model policy, or user-owned output changed.

**Step 2: Commit**

Run: `git commit -m "docs(architecture): synchronize application runtime"`

**Step 3: Report evidence to Issue #144 and close it**

Include the exact commit, focused/full test counts, Planner evaluation result, browser acceptance report, source-analysis inventory totals, stale-reference scan, and historical-boundary proof. Do not push this new branch until the next explicit “继续”, preserving the established serial workflow.
