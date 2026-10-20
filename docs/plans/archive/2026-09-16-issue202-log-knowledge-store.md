# SQLite Log Knowledge Store Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `tdd` to execute this plan task-by-task.

**Goal:** Replace the legacy SQLite/NumPy/JSON log-pattern state with one transactional SQLite repository that safely stores reviewable log knowledge.

**Architecture:** Deepen `agent.tools.log_pattern_store` behind a small typed repository API. SQLite owns schema versioning, state invariants, bounded samples, review transitions, replacement links, and legacy migration; callers inject a database path for tests, while production resolves one environment override or the existing default path. This issue does not implement user submission UI, candidate ranking, or classification replay.

**Tech Stack:** Python standard library (`sqlite3`, `dataclasses`, `hashlib`, `json`, `pathlib`), pytest, SQLite partial indexes and triggers.

---

### Task 1: Lock the path and schema lifecycle contract

**Files:**
- Create: `tests/test_log_knowledge_repository.py`
- Modify: `agent/tools/log_pattern_store.py`

1. RED: assert the default database remains `config/log_patterns.db`, `LOG_KNOWLEDGE_DB_PATH` overrides it, a supplied `db_path` wins, and initialization enables foreign keys.
2. RED: initialize the same empty database twice and assert one current schema version plus the required application/sample tables, indexes, checks, and triggers.
3. GREEN: add `resolve_log_knowledge_db_path(db_path=None)` and a `LogKnowledgeRepository` whose constructor initializes the schema transactionally.
4. Use stable JSON encoding: `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` and UTC ISO-8601 timestamps.
5. Run `python -X utf8 -m pytest -q tests/test_log_knowledge_repository.py` after each RED/GREEN step.

### Task 2: Store applications and bounded samples

**Files:**
- Modify: `tests/test_log_knowledge_repository.py`
- Modify: `agent/tools/log_pattern_store.py`

1. RED: create a pending application through a typed public input and read it back through a review-only detail API.
2. RED: reject status values outside `pending`, `approved`, and `rejected`; keep selection mode and normalized extractor identity explicit.
3. RED: add repeated samples and assert SHA-256 deduplication, a hard maximum of 10 unique samples, and deterministic retention order.
4. RED: assert the ordinary approved-candidate projection contains recipe facts but never raw sample text.
5. GREEN: add frozen dataclasses for the application input, approved candidate, and review detail; implement atomic insert and safe projections.

### Task 3: Enforce review and cleanup transactions

**Files:**
- Modify: `tests/test_log_knowledge_repository.py`
- Modify: `agent/tools/log_pattern_store.py`

1. RED: approve a pending application and assert only approved rows are returned by ordinary retrieval.
2. RED: reject requires a non-empty reason and records reviewer plus UTC review time; deleting pending or approved rows is denied.
3. RED: deleting a rejected row cascades its samples.
4. RED: approving a competing application without a replacement reason fails; with a reason, one transaction rejects the old approval, links both records, and approves the new record.
5. RED: inject a failure between replacement updates and assert the entire transaction rolls back with the old approval still active.
6. GREEN: implement `approve`, `reject`, and `delete_rejected` with `BEGIN IMMEDIATE`, one approved-row partial unique index per structure/selection scope, and stable exceptions that contain no raw logs.

### Task 4: Migrate the current legacy schema safely

**Files:**
- Modify: `tests/test_log_knowledge_repository.py`
- Modify: `agent/tools/log_pattern_store.py`

1. RED: construct the current `log_patterns`/`pattern_samples` schema in a temporary database and initialize the new repository.
2. RED: assert a reconstructable recipe whose saved samples replay successfully becomes `pending`; an invalid JSON, extractor, or sample becomes `rejected` with a stable migration reason.
3. RED: assert samples are preserved subject to deduplication/limit, no legacy row becomes approved, and running migration twice creates no duplicates.
4. RED: assert missing or stale `.npy`/JSON sidecars do not affect startup or migration, and an injected migration failure rolls back all new rows.
5. GREEN: perform versioned legacy migration in the initialization transaction, keyed by legacy source ID; use standard-library replay checks and never read or rebuild sidecars.

### Task 5: Retire sidecars and isolate the explicit-submission seam

**Files:**
- Modify: `tests/test_log_knowledge_store_contract.py`
- Modify: `agent/tools/log_pattern_store.py`
- Modify: `agent/tools/pipeline/common/knowledge_store.py`
- Modify: `agent/tools/pipeline/log_classifier.py`
- Modify: `agent/tools/pipeline/log_header_processor.py`
- Modify: `agent/core/field_retriever.py`
- Modify: `agent/core/embedding_client.py`

1. RED: assert the log knowledge module has no NumPy/embedding/metadata-sidecar runtime dependency.
2. RED: assert compatibility storage reports failure when the repository does not create a row; retain this seam for #203's explicit submission flow.
3. RED: assert successful JSON, KV, and Header classification never imports or calls knowledge storage and therefore cannot create a pending application automatically.
4. RED: assert Header validation, exception, and success diagnostics expose only stable categories, counts, and lengths—never raw samples, body previews, or exception text.
5. GREEN: remove the sidecar constants, update/read paths, vector retrieval, and obsolete imports while leaving standard-field embedding behavior untouched.
6. GREEN: remove automatic storage imports/calls from normal classification. The compatibility wrapper remains available only for #203 to invoke after an explicit user submission; do not add retrieval/replay or UI behavior from later issues.
7. Run the repository, compatibility seam, Header, lineage, and full-enumeration focused tests.

### Task 6: Synchronize architecture documentation and verify

**Files:**
- Modify: `CONTEXT.md`
- Create: `docs/adr/0012-sqlite-log-knowledge-single-source.md`
- Modify: `docs/architecture/领域能力目录.md`
- Modify: `docs/architecture/pipeline架构说明.md`
- Regenerate: `docs/source-code-analysis.html`

1. Document SQLite as the only runtime fact source, three review states, bounded samples, atomic replacement, and safe legacy migration; keep candidate ranking/replay and UI explicitly out of scope.
2. Run `python -X utf8 scripts/generate_source_code_analysis.py` after production Python changes.
3. Run focused repository and knowledge-store tests.
4. Run `python -X utf8 -m pytest -q` and confirm the complete suite passes.
5. Confirm `git diff --check`, no secrets or `.env` are tracked, no sidecar access remains in log knowledge code, and unrelated main-worktree files are absent.
