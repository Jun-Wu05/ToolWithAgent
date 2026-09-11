# Domain Capability Deepening PRD Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce and publish an evidence-backed, headless, human-reviewable parent PRD for ToolWithAgent domain capability deepening without changing production behavior.

**Architecture:** Treat the final Application runtime dependency graph and generated source analysis as the evidence baseline. Separate domain boundaries, technical architecture decisions, test seams, deletion audits, and explicit human decisions; publish only a planning Issue and make no production refactor.

**Tech Stack:** Python AST/import analysis, Git, GitHub Issues via `gh`, Markdown PRD, existing `CONTEXT.md` and ADRs.

---

### Task 1: Establish the governed baseline

**Files:**
- Read: `CONTEXT.md`
- Read: `docs/adr/*.md`
- Read: `docs/source-code-analysis.html`
- Read: GitHub Issues `#130`, `#144`, `#145`

**Step 1:** Confirm #144 is completed and pushed, and record the exact baseline commit.

**Step 2:** Read the domain vocabulary and every relevant ADR without rewriting historical decisions.

**Step 3:** Record the headless UI mode and the explicit no-refactor/no-delete boundary.

### Task 2: Build the domain-capability evidence matrix

**Files:**
- Inspect: `agent/core/field_retriever.py`
- Inspect: `agent/tools/`
- Inspect: `agent/shared/`
- Inspect: `agent/tools/pipeline/`
- Inspect: `application/adapters/field_skill.py`
- Inspect: `skills/*/scripts/*.py`
- Inspect: `web/constants.py`
- Inspect: `agent/tools/base64_tool.py`
- Create: `outputs/issue145-domain-evidence/20260831/evidence.md`

**Step 1:** Measure production files, line counts, public symbols, imports, callers, package re-exports, dynamic registrations, and tests.

**Step 2:** Classify candidates by responsibility depth and coupling rather than raw size.

**Step 3:** For each deletion candidate, prove or disprove production imports, dynamic loading, package-level re-exports, tests, and external dependency evidence.

**Step 4:** Propose line-budget ranges as navigation signals only, never as quality scores.

### Task 3: Confirm human decisions and test seams

**Files:**
- Update: `docs/plans/2026-08-31-issue145-domain-deepening-prd.md`

**Step 1:** Present the recommended phase order and ask the maintainer to confirm the first implementation tranche.

**Step 2:** Present the highest-level proposed test seams and ask the maintainer to confirm them.

**Step 3:** Keep disputed candidates in an evidence-only audit lane rather than deciding deletion.

### Task 4: Draft the headless parent PRD

**Files:**
- Create: `docs/prd/domain-capability-deepening.md`

**Step 1:** Write the problem statement, solution, detailed `US-n` stories, implementation decisions, test decisions, non-goals, risks, and phased roadmap using `CONTEXT.md` terminology.

**Step 2:** Cover StandardFieldCatalog, domain capability directory, log classification strategy, Field Skill Adapter deepening, hotspots, responsibility depth, line budgets, merge/split candidates, and deletion evidence gates.

**Step 3:** Mark every irreversible scope choice and deletion as human approval required.

**Step 4:** Validate that the PRD contains no UI chapter, no source file prescriptions, no code snippets, and no unapproved implementation work.

### Task 5: Publish and hand back to human review

**Files:**
- Read: `docs/prd/domain-capability-deepening.md`

**Step 1:** Publish the approved PRD as a new GitHub parent Issue with `enhancement` and `ready-for-human`.

**Step 2:** Link the new parent PRD from #145 and record the evidence artifact and open decisions.

**Step 3:** Commit only the local PRD/evidence index changes required by #145; exclude all pre-existing user files and `outputs/` evidence.

**Step 4:** Close #145 when the draft parent PRD exists and is explicitly queued for human review; do not create implementation Issues until that review completes.

