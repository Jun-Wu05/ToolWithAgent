# #416 Shared threat/operation result implementation plan

**Goal:** Show six columns: 子规则 / 事件名称 / 事件级别 / 判定来源 / 威胁/操作类型 / 状态. Event names contain no extra tag text.

**Architecture:** Keep existing threat-only report fields compatible. Reuse one actual fixed/reference binding resolver in application/threat_report.py. The owner-only V2 mapping view adds neutral type_source/type_values from stored configuration for operations and the recorded chain conclusion for threats. Old artifacts become readable without mutation; no shared Contracts extension or extra model call.

**Tech Stack:** Python/pytest, existing protected mapping API, React/Vitest.

1. Add red tests for actual fixed values, mapped references, direct references, no samples, no binding and empty binding.
2. Add an old-artifact API regression proving success, read-only projection, owner isolation and absence of operation values from conversation/events.
3. Add the exact six-header UI assertion, plain event names, fixed/reference source labels, and legacy missing-evidence fallback.
4. Implement the shared binding resolver and protected projection; preserve failed/uncertain threat outcomes rather than recomputing a success from retained configuration.
5. Regenerate source-code-analysis.html, run full root/backend/frontend tests, lint/build and independent Review.
6. Commit this #416 iteration; update the combined acceptance checkout and checklist. User restarts services and performs browser review; no automatic browser operation or development-line merge.
