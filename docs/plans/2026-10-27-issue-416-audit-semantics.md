# #416 Audit event semantics implementation plan

**Goal:** Audit/information events show operational semantics; threat fields explicitly say not applicable.

**Architecture:** build_threat_report_rows writes the non-threat applicability once. MappingWorkspace makes the threat-only column scope explicit and labels operational rows; legacy information-level rows receive the same presentation. Threat and uncertain rows preserve their existing source/result behavior. No classifier, mapping, or business configuration changes.

**Tech Stack:** Python/pytest and React/Vitest.

1. Establish a green isolated baseline.
2. Add mixed audit/threat/uncertain report tests and a protected MappingWorkspace display regression; run to red.
3. Change application/threat_report.py and MappingWorkspace.tsx; run to green.
4. Regenerate source-code-analysis.html; run full root/backend/frontend tests, lint/build.
5. Review changes and prepare browser acceptance with audit and threat rules in one result.
