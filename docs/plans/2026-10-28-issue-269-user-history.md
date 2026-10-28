# Issue #269 User Task, Run, and Artifact History Implementation Plan

**Goal:** Let a user browse only their own Tasks and Runs across conversations, return to the source conversation, and inspect versioned Artifacts through the existing single drawer.

**Architecture:** Query the existing SQLite Task, Run, Artifact, and edge tables; do not add a second history store. Keep owner checks in Store methods and expose compact paginated REST projections. Reuse the workbench shell and its existing run/artifact drawer for detail, cancellation, retry, preview, and download.

**Tech Stack:** FastAPI, SQLite, React, TypeScript, pytest, Vitest.

## 1. Baseline and contract

- Verify `github/codex/v2-development@78c7aa701420bc1140ea79056757575c511c24f9` contains `github/master@ff6775d18865e1a23b7a10a09cd2063ada971137` and that this branch starts clean.
- Run root and V2 backend full pytest with worktree-local `--basetemp`; run frontend Vitest, lint, and build after `npm ci`.
- Read #269, product PRD US-2/US-11/US-12 and pages `tasks`, `runs`, `workbench`. Retain the existing owner-only Run actions and single drawer.

## 2. Owner-scoped Task and Run pages

**Files:** `v2/backend/tests/test_user_history.py`, `v2/backend/toolwithagent_v2/infrastructure/store.py`, `v2/backend/toolwithagent_v2/api/app.py`.

1. Write failing API tests: create two users and multiple conversations; assert `/api/v2/tasks` and `/api/v2/runs` return only the current user's records, stable newest-first pagination, status filtering, source conversation/message IDs, and no other user's content.
2. Run `python -X utf8 -m pytest v2/backend/tests/test_user_history.py -q --tb=short`; expect endpoint 404 or failed assertions.
3. Add bounded `Store.user_tasks` and `Store.user_runs` projections using owner predicates in SQL. Reuse `_run` and existing joins; return IDs, safe state, timestamps, conversation title/ID and current/latest Run pointer. Validate page/status values at the API boundary.
4. Run the same tests; expect green. Confirm Developer has no new write path.

## 3. Artifact provenance and download audit

**Files:** `v2/backend/tests/test_user_history.py`, `v2/backend/toolwithagent_v2/infrastructure/store.py`.

1. Add failing tests for Artifact version, source edge IDs, stale status and protected preview/download. Test a field-mapping download creates exactly one `artifact_download` audit row; a denied or corrupt download creates none.
2. Project version and source IDs from existing `artifacts`/`artifact_edges` rows. Keep content behind the existing owner-only `/content` route.
3. Move field-mapping download into the shared success path in `artifact_download` so all successful kinds audit after bytes are prepared. Keep the existing filename logic.
4. Run the focused tests; expect green.

## 4. User history UI and single drawer

**Files:** `v2/frontend/src/api.ts`, `v2/frontend/src/App.tsx`, `v2/frontend/src/WorkspaceViews.tsx`, `v2/frontend/src/UserHistory.tsx`, `v2/frontend/src/UserHistory.test.tsx`, and existing stylesheet/test files only if needed.

1. Write failing Vitest scenarios for Task/Run empty and filtered lists, cross-conversation navigation, queued/running/waiting/succeeded/failed/cancelling/cancelled states, and version/source display in the one drawer.
2. Add typed API methods for owner lists. Render Task and Run views inside the existing shell; do not introduce a second drawer. Selection changes conversation first, then opens its Run or Artifact through existing callbacks. Keep unsent composer text and role guards intact.
3. Run focused Vitest; expect green. Check keyboard focus and narrow layout with existing primitives.

## 5. Validation, review, and handoff

1. Regenerate `docs/source-code-analysis.html` if production Python changes.
2. Run full root pytest, V2 backend pytest, frontend Vitest, lint, and build; inspect `git diff --check` and owner/download paths.
3. Record exact branch and HEAD, automation results, remaining manual browser scenarios, and combined acceptance boundary in `docs/design/v2-269-acceptance.md`.
4. Commit in logical groups, push the short branch, show the complete PR body to the user before publishing, and target `codex/v2-development` with `Closes #269`.
