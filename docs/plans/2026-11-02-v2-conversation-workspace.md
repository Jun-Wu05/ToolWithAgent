# V2 Conversation Workspace Implementation Plan

**Goal:** Implement Issue #430 on the V2 development line using the approved conversation, trace, and resource workspace behavior.

**Architecture:** Keep the existing conversation and mapping components mounted while moving their presentation into a two-view conversation shell and a right resource workspace. Reuse the current Run detail and artifact APIs. Keep server draft revision and permission checks as the source of truth.

**Tech stack:** React 18, TypeScript, Vite, Vitest, existing FastAPI V2 contracts.

## 1. Baseline and contracts

- Use the isolated issue branch from github/codex/v2-development; run full pytest before changes.
- Trace App.tsx, ConversationTimeline.tsx, WorkspaceViews.tsx, MappingWorkspace.tsx, api.ts, and existing workbench CSS and tests.
- Keep source file metadata with its conversation message; the approved right workspace has only mapping and results tabs.

## 2. Conversation and trace

- Update App.tsx to expose conversation and trace as views of the active conversation.
- Add a target Run ID to ExecutionTrace in WorkspaceViews.tsx so a message Run entry switches views, locates, and expands the matching row. Reuse TraceDetail and remove the duplicate execution side panel path.
- Update App.test.tsx and WorkspaceViews.test.tsx for navigation, location, return state, and absent Run cases. Run targeted frontend tests.

## 3. Right resource workspace

- Add one resource tab model in App.tsx: one mapping tab and one results tab. Keep it per conversation and reset on identity/conversation change.
- Move MappingWorkspace and the real artifact list/detail into the right area; keep the mapping component mounted while hidden. Make whole-workspace collapse preserve tabs, width, selected resources, draft, filters, and conversation scroll. Closing the last tab collapses the area.
- Add pointer and keyboard divider controls in App.tsx and workbench CSS. Use responsive overlay when the viewport is 1200px or narrower so the left navigation does not force page-wide horizontal scrolling.
- Add focused tests for tab identity, close/collapse distinction, pending draft guards, resize, and responsive state. Run targeted frontend tests.

## 4. Results and finish

- Wire real artifacts and versions to the single results tab and return a result entry to the related conversation message only after server success.
- Preserve role checks, true Run/Skill/Tool evidence, old independent history labels, and existing error and cancellation states.
- Run frontend tests, lint, build, full pytest. Hand off 1440px and 1024px real Excel/session/Run inspection as the separate business acceptance gate; record its evidence before claiming acceptance complete.
