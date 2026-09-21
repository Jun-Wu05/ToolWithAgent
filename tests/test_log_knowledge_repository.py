from __future__ import annotations

from pathlib import Path


def test_repository_path_precedence_and_foreign_keys(tmp_path, monkeypatch):
    from agent.tools.log_pattern_store import (
        LogKnowledgeRepository,
        resolve_log_knowledge_db_path,
    )

    monkeypatch.delenv("LOG_KNOWLEDGE_DB_PATH", raising=False)
    assert resolve_log_knowledge_db_path() == Path("config/log_patterns.db")

    configured_path = tmp_path / "configured.db"
    monkeypatch.setenv("LOG_KNOWLEDGE_DB_PATH", str(configured_path))
    assert resolve_log_knowledge_db_path() == configured_path

    supplied_path = tmp_path / "supplied.db"
    repository = LogKnowledgeRepository(supplied_path)
    assert repository.db_path == supplied_path
    with repository.connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_schema_initialization_is_idempotent_and_complete(tmp_path):
    from agent.tools.log_pattern_store import LogKnowledgeRepository

    db_path = tmp_path / "knowledge.db"
    LogKnowledgeRepository(db_path)
    repository = LogKnowledgeRepository(db_path)

    with repository.connect() as connection:
        assert connection.execute(
            "SELECT version FROM log_knowledge_schema_version"
        ).fetchall() == [(1,)]
        objects = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT type, name FROM sqlite_master "
                "WHERE name LIKE 'log_knowledge_%'"
            )
        }

    assert ("table", "log_knowledge_applications") in objects
    assert ("table", "log_knowledge_samples") in objects
    assert ("index", "log_knowledge_one_approved_scope") in objects
    assert ("trigger", "log_knowledge_samples_max_ten") in objects


def test_pending_application_round_trips_through_review_detail(tmp_path):
    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")
    application_id = repository.create_application(
        LogKnowledgeApplicationInput(
            recipe_version=1,
            structure_hash="structure-1",
            structure_tokens=("type", "=", "{value}"),
            format_type="kv",
            format_spec={"delimit": ";", "tab": "="},
            selection_mode="explicit",
            feature_field="Type",
            extractor_type="field_path",
            extractor_spec={"path": "Type"},
            submitter="alice",
            submission_note="review this recipe",
        ),
        samples=["Type=Auth; User=a"],
    )

    detail = repository.get_review_detail(application_id)
    assert detail.status == "pending"
    assert detail.application.feature_field == "Type"
    assert detail.application.extractor_spec == {"path": "Type"}
    assert detail.samples == ("Type=Auth; User=a",)


def test_atomic_submission_is_idempotent_and_rejected_can_resubmit(tmp_path):
    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")
    application = LogKnowledgeApplicationInput(
        1, "structure-1", ("kv",), "kv", {}, "explicit", "type",
        "field_path", {"path": "type"}, "alice",
    )

    created = repository.submit_application(application, ["type=a", "type=b"])
    duplicate = repository.submit_application(application, ["type=b", "type=c"])

    assert created.status == "created"
    assert duplicate.status == "pending_duplicate"
    assert duplicate.application_id == created.application_id
    assert repository.get_review_detail(created.application_id).samples == (
        "type=a", "type=b", "type=c",
    )

    repository.reject(created.application_id, reviewer="admin", reason="bad recipe")
    resubmitted = repository.submit_application(application, ["type=d"])
    assert resubmitted.status == "created"
    assert resubmitted.application_id != created.application_id

    repository.approve(resubmitted.application_id, reviewer="admin")
    approved = repository.submit_application(application, ["type=secret"])
    assert approved.status == "already_approved"
    assert approved.application_id == resubmitted.application_id
    assert "type=secret" not in repository.get_review_detail(
        resubmitted.application_id
    ).samples


def test_concurrent_atomic_submission_recovers_to_one_pending_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")
    application = LogKnowledgeApplicationInput(
        1, "structure-1", ("kv",), "kv", {}, "automatic", "",
        "field_path", {"path": "type"}, "alice",
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda sample: repository.submit_application(application, [sample]),
                ("type=a", "type=b"),
            )
        )

    assert {result.status for result in results} == {"created", "pending_duplicate"}
    assert len({result.application_id for result in results}) == 1
    assert set(repository.get_review_detail(results[0].application_id).samples) == {
        "type=a", "type=b",
    }


def test_samples_are_sha256_deduplicated_bounded_and_ordered(tmp_path):
    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")
    application_id = repository.create_application(
        LogKnowledgeApplicationInput(
            1, "structure-1", ("type",), "kv", {}, "automatic", "",
            "field_path", {"path": "Type"}, "alice",
        )
    )
    repository.add_samples(
        application_id,
        ["sample-0", "sample-0", *[f"sample-{index}" for index in range(1, 13)]],
    )

    assert repository.get_review_detail(application_id).samples == tuple(
        f"sample-{index}" for index in range(10)
    )
    with repository.connect() as connection:
        hashes = [
            row[0]
            for row in connection.execute(
                "SELECT sample_hash FROM log_knowledge_samples ORDER BY id"
            )
        ]
    import hashlib

    assert hashes == [
        hashlib.sha256(f"sample-{index}".encode()).hexdigest()
        for index in range(10)
    ]


def test_only_approved_candidates_are_retrievable_without_raw_samples(tmp_path):
    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")
    application_id = repository.create_application(
        LogKnowledgeApplicationInput(
            1, "structure-1", ("type",), "kv", {}, "automatic", "",
            "field_path", {"path": "Type"}, "alice",
        ),
        samples=["Type=Auth; secret=raw"],
    )
    assert repository.list_approved_candidates("structure-1", "automatic") == ()

    repository.approve(application_id, reviewer="admin")
    candidates = repository.list_approved_candidates("structure-1", "automatic")

    assert len(candidates) == 1
    assert candidates[0].extractor_spec == {"path": "Type"}
    assert not hasattr(candidates[0], "samples")
    assert "secret=raw" not in repr(candidates[0])


def test_reject_requires_reason_and_only_rejected_rows_can_be_deleted(tmp_path):
    import pytest

    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeError,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")
    application = LogKnowledgeApplicationInput(
        1, "structure-1", ("type",), "kv", {}, "automatic", "",
        "field_path", {"path": "Type"}, "alice",
    )
    pending_id = repository.create_application(application, samples=["raw-secret"])
    with pytest.raises(ValueError, match="reason"):
        repository.reject(pending_id, reviewer="admin", reason=" ")
    with pytest.raises(LogKnowledgeError, match="rejected"):
        repository.delete_rejected(pending_id)

    repository.reject(pending_id, reviewer="admin", reason="invalid recipe")
    detail = repository.get_review_detail(pending_id)
    assert detail.status == "rejected"
    assert detail.reviewer == "admin"
    assert detail.review_reason == "invalid recipe"
    assert detail.reviewed_at.endswith("+00:00")

    repository.delete_rejected(pending_id)
    with repository.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM log_knowledge_samples WHERE application_id = ?",
            (pending_id,),
        ).fetchone() == (0,)


def test_competing_approval_atomically_replaces_the_active_recipe(tmp_path):
    import pytest

    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeError,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")

    def application(path: str):
        return LogKnowledgeApplicationInput(
            1, "same-structure", ("type",), "kv", {}, "automatic", "",
            "field_path", {"path": path}, "alice",
        )

    old_id = repository.create_application(application("Type"))
    repository.approve(old_id, reviewer="admin")
    new_id = repository.create_application(application("event_type"))

    with pytest.raises(LogKnowledgeError, match="replacement reason"):
        repository.approve(new_id, reviewer="admin")

    repository.approve(new_id, reviewer="admin", reason="better evidence")

    old_detail = repository.get_review_detail(old_id)
    new_detail = repository.get_review_detail(new_id)
    assert (old_detail.status, old_detail.replaced_by_application_id) == (
        "rejected", new_id,
    )
    assert (new_detail.status, new_detail.replaces_application_id) == (
        "approved", old_id,
    )
    assert repository.list_approved_candidates(
        "same-structure", "automatic"
    )[0].application_id == new_id


def test_replaced_application_can_be_deleted_without_harming_new_approval(tmp_path):
    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")

    def application(path: str):
        return LogKnowledgeApplicationInput(
            1, "same-structure", ("type",), "kv", {}, "automatic", "",
            "field_path", {"path": path}, "alice",
        )

    old_id = repository.create_application(
        application("Type"), samples=["Type=Auth; secret=old"]
    )
    repository.approve(old_id, reviewer="admin")
    new_id = repository.create_application(application("event_type"))
    repository.approve(new_id, reviewer="admin", reason="better evidence")

    repository.delete_rejected(old_id)

    with repository.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM log_knowledge_samples WHERE application_id = ?",
            (old_id,),
        ).fetchone() == (0,)
    new_detail = repository.get_review_detail(new_id)
    assert new_detail.status == "approved"
    assert new_detail.replaces_application_id is None
    assert repository.list_approved_candidates(
        "same-structure", "automatic"
    )[0].application_id == new_id


def test_automatic_applications_share_one_empty_feature_field_scope(tmp_path):
    import sqlite3

    import pytest

    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeError,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")

    def application(feature_field: str, path: str):
        return LogKnowledgeApplicationInput(
            1, "same-structure", ("type",), "kv", {}, "automatic",
            feature_field, "field_path", {"path": path}, "alice",
        )

    old_id = repository.create_application(application("Type", "Type"))
    assert repository.get_review_detail(old_id).application.feature_field == ""
    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE log_knowledge_applications SET feature_field = 'Type' "
                "WHERE id = ?",
                (old_id,),
            )

    repository.approve(old_id, reviewer="admin")
    new_id = repository.create_application(
        application("event_type", "event_type")
    )
    with pytest.raises(LogKnowledgeError, match="replacement reason"):
        repository.approve(new_id, reviewer="admin")


def test_competing_approval_failure_rolls_back_the_replacement(tmp_path, monkeypatch):
    import pytest

    from agent.tools.log_pattern_store import (
        LogKnowledgeApplicationInput,
        LogKnowledgeRepository,
    )

    repository = LogKnowledgeRepository(tmp_path / "knowledge.db")
    base = dict(
        recipe_version=1, structure_hash="same-structure",
        structure_tokens=("type",), format_type="kv", format_spec={},
        selection_mode="automatic", feature_field="", extractor_type="field_path",
        submitter="alice",
    )
    old_id = repository.create_application(
        LogKnowledgeApplicationInput(**base, extractor_spec={"path": "Type"})
    )
    repository.approve(old_id, reviewer="admin")
    new_id = repository.create_application(
        LogKnowledgeApplicationInput(**base, extractor_spec={"path": "event_type"})
    )
    monkeypatch.setattr(
        repository,
        "_after_replacement_update",
        lambda: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )

    with pytest.raises(RuntimeError, match="injected failure"):
        repository.approve(new_id, reviewer="admin", reason="better evidence")

    assert repository.get_review_detail(old_id).status == "approved"
    assert repository.get_review_detail(new_id).status == "pending"


def test_legacy_rows_migrate_idempotently_without_automatic_approval(tmp_path):
    import json
    import sqlite3

    from agent.tools.log_pattern_store import LogKnowledgeRepository

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE log_patterns (
                id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL,
                format TEXT NOT NULL, meta_json TEXT NOT NULL,
                created_at TEXT, updated_at TEXT, use_count INTEGER DEFAULT 0,
                last_used_at TEXT
            );
            CREATE TABLE pattern_samples (
                id INTEGER PRIMARY KEY, pattern_id INTEGER NOT NULL,
                sample_log TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO log_patterns(id, fingerprint, format, meta_json) "
            "VALUES (1, 'KV|Type|recipe', 'kv', ?)",
            (json.dumps({
                "selection_mode": "automatic",
                "feature_field": "Type",
                "feature_identifier": r"Type=([^;]+)",
            }),),
        )
        connection.execute(
            "INSERT INTO pattern_samples(pattern_id, sample_log) VALUES (1, 'Type=Auth;User=a')"
        )
        connection.execute(
            "INSERT INTO log_patterns(id, fingerprint, format, meta_json) "
            "VALUES (2, 'broken', 'kv', '{not-json')"
        )
        connection.execute(
            "INSERT INTO pattern_samples(pattern_id, sample_log) VALUES (2, 'raw-secret')"
        )
        connection.execute(
            "INSERT INTO log_patterns(id, fingerprint, format, meta_json) "
            "VALUES (3, 'missing-mode', 'kv', ?)",
            (json.dumps({"feature_identifier": r"Type=([^;]+)"}),),
        )
        connection.execute(
            "INSERT INTO pattern_samples(pattern_id, sample_log) VALUES (3, 'Type=Mail')"
        )

    repository = LogKnowledgeRepository(db_path)
    LogKnowledgeRepository(db_path)

    with repository.connect() as connection:
        migrated = connection.execute(
            """
            SELECT legacy_source_id, status, review_reason
            FROM log_knowledge_applications ORDER BY legacy_source_id
            """
        ).fetchall()
        assert connection.execute(
            "SELECT count(*) FROM log_knowledge_applications"
        ).fetchone() == (3,)

    assert migrated[0][:2] == (1, "pending")
    assert migrated[1] == (2, "rejected", "legacy metadata invalid")
    assert migrated[2] == (
        3, "rejected", "legacy_selection_mode_missing",
    )
    assert repository.get_review_detail(1).samples == ("Type=Auth;User=a",)


def test_legacy_explicit_row_without_feature_field_is_rejected_idempotently(
    tmp_path,
):
    import json
    import sqlite3

    from agent.tools.log_pattern_store import LogKnowledgeRepository

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE log_patterns (
                id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL,
                format TEXT NOT NULL, meta_json TEXT NOT NULL,
                created_at TEXT, updated_at TEXT, use_count INTEGER DEFAULT 0,
                last_used_at TEXT
            );
            CREATE TABLE pattern_samples (
                id INTEGER PRIMARY KEY, pattern_id INTEGER NOT NULL,
                sample_log TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO log_patterns(id, fingerprint, format, meta_json) "
            "VALUES (1, 'explicit-missing-field', 'kv', ?)",
            (json.dumps({
                "selection_mode": "explicit",
                "feature_identifier": r"Type=([^;]+)",
            }),),
        )
        connection.execute(
            "INSERT INTO pattern_samples(pattern_id, sample_log) "
            "VALUES (1, 'Type=Auth')"
        )
        connection.execute(
            "INSERT INTO log_patterns(id, fingerprint, format, meta_json) "
            "VALUES (2, 'automatic-valid', 'kv', ?)",
            (json.dumps({
                "selection_mode": "automatic",
                "feature_identifier": r"Type=([^;]+)",
            }),),
        )
        connection.execute(
            "INSERT INTO pattern_samples(pattern_id, sample_log) "
            "VALUES (2, 'Type=Mail')"
        )

    repository = LogKnowledgeRepository(db_path)
    LogKnowledgeRepository(db_path)

    detail = repository.get_review_detail(1)
    assert detail.status == "rejected"
    assert detail.review_reason == "legacy_feature_field_missing"
    assert detail.application.selection_mode == "explicit"
    assert detail.application.feature_field
    assert repository.get_review_detail(2).status == "pending"
    assert repository.list_approved_candidates(
        detail.application.structure_hash,
        detail.application.selection_mode,
        detail.application.feature_field,
    ) == ()
    with repository.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM log_knowledge_applications"
        ).fetchone() == (2,)


def test_legacy_migration_ignores_sidecars_and_rolls_back_on_failure(
    tmp_path, monkeypatch
):
    import json
    import sqlite3

    import pytest

    from agent.tools.log_pattern_store import LogKnowledgeRepository

    db_path = tmp_path / "legacy.db"
    (tmp_path / "log_patterns_embeddings.npy").write_bytes(b"not-a-numpy-file")
    (tmp_path / "log_patterns_meta.json").write_text("{broken", encoding="utf-8")
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE log_patterns (
                id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL,
                format TEXT NOT NULL, meta_json TEXT NOT NULL,
                created_at TEXT, updated_at TEXT, use_count INTEGER DEFAULT 0,
                last_used_at TEXT
            );
            CREATE TABLE pattern_samples (
                id INTEGER PRIMARY KEY, pattern_id INTEGER NOT NULL,
                sample_log TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO log_patterns(id, fingerprint, format, meta_json) "
            "VALUES (1, 'recipe', 'kv', ?)",
            (json.dumps({
                "selection_mode": "automatic",
                "feature_identifier": r"Type=([^;]+)",
            }),),
        )
        connection.execute(
            "INSERT INTO pattern_samples(pattern_id, sample_log) VALUES (1, 'Type=Auth')"
        )

    monkeypatch.setattr(
        LogKnowledgeRepository,
        "_after_legacy_migration_row",
        lambda _self: (_ for _ in ()).throw(RuntimeError("migration failure")),
    )
    with pytest.raises(RuntimeError, match="migration failure"):
        LogKnowledgeRepository(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT count(*) FROM sqlite_master
            WHERE name = 'log_knowledge_applications'
            """
        ).fetchone() == (0,)
