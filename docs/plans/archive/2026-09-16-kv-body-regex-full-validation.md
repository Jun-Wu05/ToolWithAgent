# KV Body Regex Full Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `diagnose` to execute this plan task-by-task.

**Goal:** Ensure every successful syslog-header-plus-KV classification extracts header-free `real_samples` for every valid input line.

**Architecture:** Generate the KV body regex from bounded structural samples, then validate it against the complete current dataset before accepting it. Preserve the authoritative full-line `sample`; if an already-validated extractor unexpectedly fails at runtime, fail closed instead of returning a syslog-prefixed body.

**Tech Stack:** Python, pytest, Markdown prompts.

---

### Task 1: Lock the mixed-boundary regression

**Files:**
- Modify: `tests/test_log_type_full_enumeration.py`
- Modify: `tests/test_match_real_samples.py`

1. Add a test with both `TYPE: key=value` and `TYPE:key=value` lines.
2. Stub the first KV-body regex as `:\\s+` and the retry as `:\\s*`.
3. Assert the first regex is rejected, the retry is accepted, and all `real_samples` are header-free.
4. Add a fail-closed postprocessor test for an unexpected regex mismatch.
5. Run the focused tests and confirm the new assertions fail before implementation.

### Task 2: Validate generated KV body regexes over the full dataset

**Files:**
- Modify: `agent/tools/pipeline/log_header_processor.py`
- Modify: `agent/prompts/kv_feature_identifier.md`

1. Select a bounded set of distinct structural examples for the prompt.
2. Change the prompt contract from one sample to multiple samples.
3. Validate compilation, one capture group, full-line coverage, non-empty body, body different from the source line, and absence of a syslog prefix.
4. Include coverage and the first failing line in the existing one-retry feedback.
5. Return `FAILED` when the second attempt still cannot cover the dataset.
6. Run the focused generation and enumeration tests.

### Task 3: Fail closed on unexpected runtime extraction misses

**Files:**
- Modify: `agent/tools/pipeline/common/llm_postprocessor.py`
- Modify: `agent/tools/pipeline/log_classifier.py`

1. Preserve the authoritative full-line `sample`.
2. Set `real_samples` to `[匹配失败]` instead of the original syslog line when a declared body extractor fails.
3. Propagate `PARTIAL` plus an explicit body-extraction `fail_reason` through batch classification.
4. Run lineage and real-sample regression tests.

### Task 4: Verify and refresh generated documentation

**Files:**
- Regenerate: `docs/source-code-analysis.html`

1. Run `python -X utf8 scripts/generate_source_code_analysis.py`.
2. Run focused log parsing tests.
3. Replay the supplied 20,000-row H3C workbook and assert 8 types, 20,000 covered lines, and header-free SSLVPN bodies.
4. Run the full pytest suite.
5. Confirm no debug probes or unrelated changes remain.
