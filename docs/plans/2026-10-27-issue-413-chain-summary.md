# #413 Chain summary implementation plan

**Goal:** Persist the actual automatic threat-chain outcome without invalidating successful field mapping.

**Architecture:** Add an optional typed summary status to StepResult, defaulting to ordinary execution status. The chain assigns its real failure/needs-input/warning/degraded outcome at source. Safe StepSummary projections consume the typed status and stable error code; no message parsing in projections. Existing reports and old snapshots remain readable.

**Tech Stack:** Python/Pydantic, pytest, existing protected V2 business_state snapshots.

1. Run the isolated root baseline green.
2. Add chain-entry regressions for failure, needs-input, degradation, success, exception and unconfirmed annotations; run to red.
3. Add a V2 freeze/restore test for the five typed outcomes; run to red.
4. Implement the optional status and source-level chain outcome; verify no business values enter the safe summary.
5. Regenerate the source snapshot and run root/backend/frontend tests, lint/build.
6. Review contracts and retained mapping publication; prepare PR text and user browser acceptance.
