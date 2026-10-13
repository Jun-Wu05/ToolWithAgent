# Issue #267 Mapping Draft Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete persistent field-mapping editing, exact-source linkage, occupancy confirmation, revision conflict handling and atomic application as a new immutable Artifact.

**Architecture:** Keep formal mapping blobs immutable. Extend the existing Draft tables with their base Artifact reference and sparse operations; owner-only queries project the Draft over the base. Apply freezes the base, operations and revision into the existing deterministic Task/Run queue; Worker publishes the Artifact, lineage, Draft completion and outbox in one SQLite transaction after lease/fence and current-base validation.

**Tech Stack:** Existing FastAPI/Pydantic, SQLite/Alembic, Application/domain helpers, React/TypeScript/Vitest. No new dependencies or model calls.

---

## Constraints and baseline

- User authorized further development while manual acceptance is deferred. Do not start services, operate browsers, invoke paid Providers or merge PRs.
- Repository AGENTS and issue workflow override generic skill execution handoffs. Execute here as Lead → Backend Builder → Frontend Builder → independent Tester → independent Reviewers.
- Branch starts at master `b79d34675c86f748c4426f0eecc5ef73b76628cf`; merge dependency #266 `647501f29e6fcc608adc8766f5958207e86e7316` before feature edits. Download naming follows master's `contracts/download_naming.py`; preserve compatibility import for #266 callers. Regenerate the source snapshot after shared Python changes.
- Workspace: `C:/Users/v-wujun/.codex/worktrees/issue-267-mapping-draft/toolswithagent`. Do not change the primary checkout or other issue worktrees.
- Requirements: issue #267, product experience §4/§14/§15, technical implementation §5.2/§6.3/§8.3, CONTEXT and ADR-0013, DESIGN §5/§6. Preserve #266 middle workspace, sidebars and Composer.
- Baseline must pass before implementation. Existing absence of per-field numeric similarity is not a reason to invent scores, thresholds or new model retrieval.

## Task 1: Persistent Draft and owner-only projection

**Files:** `v2/backend/alembic/versions/0003_mapping_drafts.py`, `v2/backend/toolwithagent_v2/infrastructure/store.py`, `v2/backend/toolwithagent_v2/api/app.py`, `v2/backend/toolwithagent_v2/runtime/mapping_projection.py`, focused tests under `v2/backend/tests/`.

1. Verify existing migrations upgrade an old V2 database. Add base reference and any minimal state/run reference needed to existing `drafts`; retain `draft_operations` and database uniqueness for active owner/base Draft.
2. Expose get-or-create Draft for a current owned published mapping and read/query/discard routes. Return stable `id`, `base_artifact_id`, `revision`, `status`, `changed_count`, `apply_run_id` and safe conversation Draft summaries.
3. Project sparse operations without changing formal blobs. Use positional sub-rule IDs plus complete source paths; duplicate display names must not conflate rules. Search/filter the entire selected sub-rule before 50-row pagination.
4. Preserve row order while editing; user choice replaces automatic evidence with `用户选择`; applying or reopening may sort by matched/unmatched/error and modified priority. Source fields and samples stay intact.
5. Verify refresh/API restart persistence, owner isolation, read-only roles, wrong-kind/corrupt/stale base rejection and history view/download compatibility.

## Task 2: Edit validation and confirmations

**Files:** backend API/Store plus smallest public domain seam if existing field assignment helpers are insufficient; backend focused tests.

1. Freeze the exact JSON contract in `v2/README.md` before any frontend changes. Follow technical §6.3 routes: standard-fields, operations PATCH, replacement-confirmations POST and same-source-candidates GET.
2. Require `If-Match` revision on saves/confirm/discard/apply. Reject stale revisions with HTTP 409 and stable `draft_revision_conflict`; never silently overwrite. Retried identical operation keys should not duplicate changes.
3. Return all legal canonical Chinese catalog names. Occupied targets remain visible with their occupant; reject aliases, unknown names, platform-fixed source fields and blacklisted targets on the server.
4. Preview replacement without altering Draft. Only explicit confirmation atomically clears the previous occupant and assigns the selected source. Cancel leaves operations and revision untouched. Clear incompatible value mappings/default metadata through the existing domain behavior when assigning a different field.
5. Return exact same-source candidates with rule name, present target and sample values. Default scope is current rule; only explicitly selected eligible rules change, and other rules with occupied targets cannot be selected. All selected changes form one operation and one save transaction.
6. Verify repeated edits, revert-to-base/no-op, cancelled replacement, TOCTOU revision change, exact dotted-path distinction, malformed scope and duplicate rule names.

## Task 3: Frozen apply and rollback

**Files:** backend Store/Worker/business_application bridge and focused tests.

1. Apply requires Idempotency-Key and the expected Draft revision. Freeze base ID/blob integrity, file/classification lineage, operation set, catalog version and audit-only Provider/Prompt versions into a new deterministic `mapping_draft_apply` Task/Run.
2. Execute deterministic domain modifications through the existing Application bridge; validate the complete edited config and target occupancy before output serialization. Do not run agents/models, fabricate an automatic continuation or rerun field mapping.
3. Before publication, recheck active Draft/revision/base, upstream currency, Run claim, leader epoch/lease and fence in the same transaction. Atomically publish new mapping Artifact/metadata/download bytes/lineage, complete Draft, propagate stale descendants, result message and outbox.
4. Failure/cancel/worker loss does not publish a new Artifact; keep the editable Draft and previous formal result. Repeated apply receipt returns the original Run; explicit retry copies frozen inputs and must still satisfy revision/base validation.
5. Guard new conversation messages in the same transaction while unapplied edits or application are present. Formal downstream inputs never read Draft operations.
6. Verify success, idempotency across Store restart, apply failure, cancelled/late publication, newer base/upstream and revised Draft, worker takeover, stale propagation, old downloads, diagnostics/privacy and pending-message behavior.

## Task 4: Frontend editor and send guard

**Files:** `v2/frontend/src/api.ts`, `MappingWorkspace.tsx`, `App.tsx`, `styles.css`, focused existing/new Vitest tests.

1. Start only after backend contract and focused checks are stable. Add typed API calls and errors; retain identity/conversation/artifact fences for all asynchronous Draft operations.
2. Show native catalog selects, current occupancy, cancel mapping, saved/saving/error/conflict/restored/applying state and modified markers. Disable dependent writes during save/apply; preserve current contents on failed operations.
3. Provide explicit replacement confirmation and exact-source linkage with conflicts disabled. Return focus to trigger, default to current rule, do not write on cancellation and do not reorder rows during edits.
4. Recover persistent Draft on reopening/refresh, retaining marks across tabs/search/pages. Revision conflicts stop writes until explicit reload; show location for validation errors and preserve editing after failed apply.
5. Add apply/discard controls. Successful apply returns to the conversation; failed apply preserves Draft and editor. A queued Run alone is not success.
6. If Composer has pending text and Draft changes, present apply-then-send / discard-then-send / return-editing. Preserve text until a successful send; apply-then-send waits for published success. Conversation/identity switches never send old pending text.
7. Run focused UI tests, all frontend tests, ESLint and production build; no browser startup/manual assertions claimed.

## Task 5: Independent verification and review

**Files:** dedicated independent tests and `v2/README.md`, verification reports under ignored local `context_summary/`.

1. Tester checks real endpoint/Worker paths and adversarial conditions independently. Production fixes remain Builder's responsibility; serialize when files/interfaces overlap.
2. Regenerate source snapshot if shared Python changed. Run root full pytest and V2 full pytest separately; run Node test/lint/build independently. Do not repeat passing checks without a new relevant change.
3. Review the feature diff against the integration baseline along Standards and Spec in two independent read-only agents. Fix every Blocking/Major and repeat only necessary regression/re-review checks.
4. Document stable routes/errors, restart behavior and actual limitations. Commit the integration baseline separately from the feature only after respective full tests are green.
5. Push `codex/issue-267-mapping-draft`, create a stacked draft PR with base `codex/issue-266-field-mapping`, `Closes #267`, dependency/integration explanation, validation counts and manual gates, and attach it to this chat. Do not merge/close/cleanup pending dependencies.

## Commands

Execute in the specified worktree with approved write permissions. Python suites run serially.

```powershell
$env:TEMP = "$PWD/tmp/system"
$env:TMP = "$PWD/tmp/system"
$env:TMPDIR = "$PWD/tmp/system"
& 'D:/install package/Anaconda1/envs/toolswithagent/python.exe' -X utf8 scripts/generate_source_code_analysis.py
& 'D:/install package/Anaconda1/envs/toolswithagent/python.exe' -X utf8 -m pytest -q --basetemp=tmp/pytest-267-root-final --junitxml=tmp/root-final.xml -o cache_dir=tmp/pytest-root-cache
$env:PYTHONPATH = 'D:/Agent/agent_design/twa-275/tmp/python-deps;C:/Users/v-wujun/.codex/worktrees/issue-267-mapping-draft/toolswithagent/v2/backend;C:/Users/v-wujun/.codex/worktrees/issue-267-mapping-draft/toolswithagent'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'D:/Agent/agent_design/twa-275/tmp/v2-venv/Scripts/python.exe' -X utf8 -c 'import sqlalchemy, alembic; import pytest; raise SystemExit(pytest.main(["v2/backend/tests", "-q", "--basetemp=tmp/pytest-267-v2-final", "--junitxml=tmp/v2-final.xml", "-o", "cache_dir=tmp/pytest-v2-cache"]))'
Set-Location v2/frontend
npm test -- --run
npm run lint
npm run build
```

Expected: all suites green, lint/build exit 0. The SQLAlchemy/Alembic preload is a test-process workaround for the already observed intermittent native Windows import crash; it is not a production code change or proof that the environment issue is fixed.
