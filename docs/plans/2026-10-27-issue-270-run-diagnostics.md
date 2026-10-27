# Developer Run Diagnostics Implementation Plan

**Goal:** Deliver a read-only, evidence-linked Run diagnosis and sanitized bundle for Developer and Admin.

**Architecture:** Reuse durable Run, event, artifact and model_calls records. Bind a V2-only diagnostic sink while a Worker executes, record allowlisted model-call evidence at the existing model seams, and expose role-checked read endpoints. Render one shared five-tab diagnosis page for Developer and Admin.

**Tech Stack:** FastAPI, SQLite, Agno, React, TypeScript, pytest, Vitest.

## 1. Evidence and storage

- Add backend tests for old Runs with no model calls, persisted call evidence, stable Run/Task/step/request IDs, and isolation across Runs.
- Add a request-scoped recording sink and call wrappers for Agno and direct HTTP model calls. Capture timing, retry, provider, model, typed error category, and bounded redacted request/response. Do not store headers, keys, raw exceptions or unreviewed logs.
- Reuse model_calls.summary_json and run_events. Add a migration only if a required field cannot be represented safely in those records.

## 2. Read-only API and bundle

- Test User/Developer/Admin list, detail and download permissions first. Developer and Admin see all Runs, User keeps their existing owner-only endpoint, and Developer cannot use write endpoints.
- Add paginated diagnostic list, detail, and JSON bundle endpoints. Include Run state, ordered timeline, calls, derived structured logs, and artifact metadata/lineage. Show absent historical evidence as “未采集”.
- Enforce the same role check on every diagnostic endpoint; bound content and redact credentials before storage and again before response/download.

## 3. Five-tab page

- Add frontend tests for failed/succeeded/running/cancelled/old Runs, five tabs, evidence jumps, filters, missing evidence, and no Developer write controls.
- Build one Developer Run page using existing V2 tokens and primitives. Admin reuses it from the Admin console; Developer gets its own route in the existing app shell. Keep the overview ordered as conclusion, impact, evidence, next action.
- Show calls in attempt order, expose safe request/response content on demand, and provide a diagnostic bundle download. Do not infer a cause when evidence is missing.

## 4. Verification and handoff

- Regenerate the source analysis snapshot after changing production Python.
- Run full root pytest, V2 backend pytest, frontend Vitest (single worker), lint, and build. Review the diff and permission/redaction paths.
- Document exact branch, HEAD, service commands, port checks and manual UI acceptance. Draft the PR body for user review before publishing.
