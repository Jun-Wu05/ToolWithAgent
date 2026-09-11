# Issue #138 Threat Runtime Migration Implementation Plan

> **For Codex:** Execute this plan with red-green-refactor; preserve all behavior seams documented in Issue #138.

**Goal:** Move threat mapping, threat parsing, threat fill, and fill dispatch into Application without changing model, Prompt, Session, error, tracing, or export-byte semantics.

**Architecture:** Application owns typed runtime steps and deterministic parsing/fill logic. Agent remains responsible for constructing `ThreatAgent` with its Prompt and model. Web keeps only composition, UI rendering, and identity-compatible re-exports.

**Tech Stack:** Python 3, Pydantic, pytest, Agno professional-agent registry.

---

### Task 1: Lock the architecture seam with failing tests

**Files:**
- Create: `tests/test_application_threat_architecture.py`

1. Assert Application threat modules have no static `web` or `chainlit` imports.
2. Assert default composition registers Application `ThreatMappingAdapter` directly.
3. Assert legacy paths re-export the identical parser and adapter objects.
4. Assert Web no longer owns `_execute_threat_mapping` or `ThreatFillAdapter` implementations.
5. Run the new test module and verify it fails for the intended missing modules.

### Task 2: Migrate parsing and threat mapping

**Files:**
- Modify: `application/parsing.py`
- Create: `application/adapters/threat_mapping.py`
- Modify: `web/parsers.py`
- Modify: `web/adapters/agent_ops.py`

1. Move threat parsing unchanged into Application and re-export it from Web.
2. Implement `ThreatMappingAdapter` with the three frozen source modes.
3. Preserve exact `json.dumps(..., ensure_ascii=False)` model input, one `ThreatAgent` call, and Session write order.
4. Make `ProfessionalAgentAdapter` a compatibility delegate only.
5. Run parser, single-intent, execution-adapter, and referenceable-artifact tests.

### Task 3: Migrate threat fill and fill dispatch

**Files:**
- Create: `application/adapters/threat_fill.py`
- Create: `application/adapters/fill.py`
- Modify: `web/adapters/config_ops.py`

1. Move threat artifact/source-field validation and stable errors unchanged.
2. Preserve enum-stale gate, fill-implies-unbind behavior, mapping order/deduplication, original `config_ref` writeback, and `changed_count` semantics.
3. Move the pure `fill_kind` dispatcher into Application.
4. Re-export identical Application classes from Web.
5. Add and run exact JSON/Base64 byte-contract tests.

### Task 4: Rewire composition and public exports

**Files:**
- Modify: `application/adapters/__init__.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/execution_adapters.py`
- Modify: `CONTEXT.md`

1. Add lazy public Application exports.
2. Register `ThreatMappingAdapter(team)` and Application `FillAdapter` directly.
3. Preserve all legacy import paths through object-identity re-exports.
4. Update the architecture map only where the migrated ownership changes.

### Task 5: Verify, commit, and close

1. Run focused architecture and threat/runtime regression tests.
2. Run the full pytest suite.
3. Inspect diff and status; stage only tracked #138 implementation/test/docs changes.
4. Commit with a conventional refactor message.
5. Post verification evidence and close Issue #138.
6. Do not push the #138 branch until the user's next explicit `继续`.
