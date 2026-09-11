# Issue #141 File Input Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move deterministic Base64, JSON, and plain-text upload decoding into Application without changing upload behavior or Primary Dataset lifecycle.

**Architecture:** A deep `application.file_input` module owns `simple_decode()` and all private parsing helpers. The Web upload adapter reads Chainlit elements, invokes this Application interface, builds the existing Primary Dataset snapshot, and emits unchanged messages. The old Agent path remains an identity-preserving compatibility re-export; unrelated Base64 encoders remain separate.

**Tech Stack:** Python, standard-library base64/json/re, Chainlit adapter seam, pytest.

---

### Task 1: Establish the Application file-input seam

**Files:**
- Create: `tests/test_application_file_input_architecture.py`
- Create: `application/file_input.py`
- Modify: `agent/core/agent.py`
- Modify: `agent/core/__init__.py`
- Modify: `web/file_handler.py`

1. Write one failing architecture test asserting Application ownership, no Web/Chainlit dependency, direct Web import, and legacy object identity.
2. Run the single test and confirm the Application module is missing.
3. Move `simple_decode()` and its private helpers unchanged; leave `simple_encode()` at its audited historical location.
4. Replace the old Agent decoder with a compatibility re-export and point lazy package export plus Web caller to Application.
5. Run the architecture test and existing upload tests.

### Task 2: Freeze Base64, JSON, and plain-text behavior

**Files:**
- Modify: `tests/test_application_file_input_architecture.py`

1. Add one parameterized public-interface test for Base64 JSON and direct JSON inputs; run it RED/GREEN.
2. Add one plain-text test for separator filtering, raw-text truncation, and the 5000-line original-log cap; run it RED/GREEN.
3. Add one nested normalize/original_log extraction test and stable empty-input error test; run it RED/GREEN.

### Task 3: Freeze Primary Dataset and user-visible upload behavior

**Files:**
- Test: `tests/test_file_handlers.py`
- Test: `tests/test_referenceable_session_artifacts.py`

1. Run the real upload seam tests for valid atomic replacement and invalid-upload preservation.
2. Confirm existing message content and Excel attachment rules remain unchanged.
3. Confirm a valid replacement clears referenceable artifacts and invalid upload preserves them.

### Task 4: Protect unrelated Base64 formats and deliver

**Files:**
- Test: existing export, fill, field-adjust, and download suites

1. Run focused Base64 artifact tests to prove no shared Codec was introduced.
2. Run `python -m compileall -q application agent web` and `git diff --check`.
3. Run the full pytest suite.
4. Stage only Issue #141 files and commit `refactor(application): migrate file input runtime`.
5. Post evidence to #141 and close it; do not push until the next explicit continuation.
