# -*- coding: utf-8 -*-
"""Reviewable log parsing knowledge backed by one SQLite fact source.

The repository owns application state, bounded review samples, approval
transactions, and legacy migration.  Candidate ranking and replay belong to
later integration work; this module deliberately has no vector or sidecar
runtime.
"""

from __future__ import annotations

import json
import os
import re as _re
import sqlite3
import time as _time
from dataclasses import dataclass
from contextlib import nullcontext
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional

from agent.shared.logger import get_logger

logger = get_logger("log_pattern_store")

# ============================================================================
# 路径配置
# ============================================================================

CURRENT_LOG_KNOWLEDGE_SCHEMA_VERSION = 1
_LEGACY_MISSING_FEATURE_FIELD = "__legacy_feature_field_missing__"


def _stable_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _application_identity(application: "LogKnowledgeApplicationInput") -> str:
    feature_field = (
        "" if application.selection_mode == "automatic" else application.feature_field
    )
    return sha256(
        _stable_json(
            {
                "recipe_version": application.recipe_version,
                "structure_hash": application.structure_hash,
                "selection_mode": application.selection_mode,
                "feature_field": feature_field,
                "extractor_type": application.extractor_type,
                "extractor_spec": application.extractor_spec,
            }
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class LogKnowledgeApplicationInput:
    recipe_version: int
    structure_hash: str
    structure_tokens: tuple[str, ...]
    format_type: str
    format_spec: dict[str, Any]
    selection_mode: str
    feature_field: str
    extractor_type: str
    extractor_spec: dict[str, Any]
    submitter: str
    submission_note: str = ""


@dataclass(frozen=True)
class ApprovedLogKnowledgeCandidate:
    application_id: int
    recipe_version: int
    structure_hash: str
    structure_tokens: tuple[str, ...]
    format_type: str
    format_spec: dict[str, Any]
    selection_mode: str
    feature_field: str
    extractor_type: str
    extractor_spec: dict[str, Any]


@dataclass(frozen=True)
class LogKnowledgeReviewDetail:
    application_id: int
    application: LogKnowledgeApplicationInput
    status: str
    samples: tuple[str, ...]
    created_at: str
    reviewed_at: str | None
    reviewer: str | None
    review_reason: str | None
    replaces_application_id: int | None
    replaced_by_application_id: int | None


@dataclass(frozen=True)
class LogKnowledgeSubmissionResult:
    """Atomic explicit-submission outcome without review sample contents."""

    status: str
    application_id: int


class LogKnowledgeError(RuntimeError):
    """Stable, non-sensitive repository failure."""


def resolve_log_knowledge_db_path(
    db_path: str | Path | None = None,
) -> Path:
    """Resolve the single SQLite path used by log knowledge."""
    if db_path is not None:
        return Path(db_path)
    configured = os.getenv("LOG_KNOWLEDGE_DB_PATH")
    return Path(configured) if configured else Path("config/log_patterns.db")


class LogKnowledgeRepository:
    """Transactional SQLite owner for reviewable log knowledge."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = resolve_log_knowledge_db_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._initialize_schema(connection)
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def create_application(
        self,
        application: LogKnowledgeApplicationInput,
        samples: list[str] | tuple[str, ...] = (),
        *,
        legacy_source_id: int | None = None,
        initial_status: str = "pending",
        migration_reason: str | None = None,
    ) -> int:
        if application.selection_mode not in {"automatic", "explicit"}:
            raise ValueError("invalid log knowledge selection mode")
        if application.extractor_type not in {"regex", "field_path"}:
            raise ValueError("invalid log knowledge extractor type")
        if initial_status not in {"pending", "rejected"}:
            raise ValueError("invalid initial log knowledge status")
        if application.recipe_version < 1:
            raise ValueError("invalid log knowledge recipe version")

        normalized_extractor = _stable_json(application.extractor_spec)
        feature_field = (
            "" if application.selection_mode == "automatic" else application.feature_field
        )
        identity = _application_identity(application)
        now = _utc_now()
        reviewed_at = now if initial_status == "rejected" else None
        reviewer = "legacy-migration" if initial_status == "rejected" else None
        reason = migration_reason if initial_status == "rejected" else None

        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    INSERT INTO log_knowledge_applications (
                        legacy_source_id, identity_hash, recipe_version,
                        structure_hash, structure_tokens_json, format_type,
                        format_spec_json, selection_mode, feature_field,
                        extractor_type, extractor_spec_json, status, submitter,
                        submission_note, created_at, reviewed_at, reviewer,
                        review_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        legacy_source_id,
                        identity,
                        application.recipe_version,
                        application.structure_hash,
                        _stable_json(application.structure_tokens),
                        application.format_type,
                        _stable_json(application.format_spec),
                        application.selection_mode,
                        feature_field,
                        application.extractor_type,
                        normalized_extractor,
                        initial_status,
                        application.submitter,
                        application.submission_note,
                        now,
                        reviewed_at,
                        reviewer,
                        reason,
                    ),
                )
                application_id = int(cursor.lastrowid)
                self._insert_samples(connection, application_id, samples)
                connection.commit()
                return application_id
        except sqlite3.Error as exc:
            raise LogKnowledgeError("log knowledge application write failed") from exc

    def get_active_application_id(
        self, application: LogKnowledgeApplicationInput
    ) -> int | None:
        """Return an existing pending/approved application with this recipe."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM log_knowledge_applications
                WHERE identity_hash = ? AND status IN ('pending', 'approved')
                """,
                (_application_identity(application),),
            ).fetchone()
        return int(row[0]) if row is not None else None

    def submit_application(
        self,
        application: LogKnowledgeApplicationInput,
        samples: list[str] | tuple[str, ...] = (),
        *,
        connection: sqlite3.Connection | None = None,
    ) -> LogKnowledgeSubmissionResult:
        """Atomically create or reuse an active application by recipe identity."""
        if application.selection_mode not in {"automatic", "explicit"}:
            raise ValueError("invalid log knowledge selection mode")
        if application.extractor_type not in {"regex", "field_path"}:
            raise ValueError("invalid log knowledge extractor type")
        if application.recipe_version < 1:
            raise ValueError("invalid log knowledge recipe version")

        identity = _application_identity(application)
        feature_field = (
            "" if application.selection_mode == "automatic" else application.feature_field
        )
        now = _utc_now()
        try:
            with (nullcontext(connection) if connection is not None else self.connect()) as active_connection:
                if connection is None:
                    active_connection.execute("BEGIN IMMEDIATE")
                active = active_connection.execute(
                    """
                    SELECT id, status FROM log_knowledge_applications
                    WHERE identity_hash = ? AND status IN ('pending', 'approved')
                    """,
                    (identity,),
                ).fetchone()
                if active is not None:
                    application_id, status = int(active[0]), str(active[1])
                    if status == "pending":
                        self._add_samples_bounded(active_connection, application_id, samples)
                        if connection is None:
                            active_connection.commit()
                        return LogKnowledgeSubmissionResult(
                            "pending_duplicate", application_id
                        )
                    if connection is None:
                        active_connection.commit()
                    return LogKnowledgeSubmissionResult(
                        "already_approved", application_id
                    )

                cursor = active_connection.execute(
                    """
                    INSERT INTO log_knowledge_applications (
                        identity_hash, recipe_version, structure_hash,
                        structure_tokens_json, format_type, format_spec_json,
                        selection_mode, feature_field, extractor_type,
                        extractor_spec_json, status, submitter,
                        submission_note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        identity,
                        application.recipe_version,
                        application.structure_hash,
                        _stable_json(application.structure_tokens),
                        application.format_type,
                        _stable_json(application.format_spec),
                        application.selection_mode,
                        feature_field,
                        application.extractor_type,
                        _stable_json(application.extractor_spec),
                        application.submitter,
                        application.submission_note,
                        now,
                    ),
                )
                application_id = int(cursor.lastrowid)
                self._add_samples_bounded(active_connection, application_id, samples)
                if connection is None:
                    active_connection.commit()
                return LogKnowledgeSubmissionResult("created", application_id)
        except sqlite3.Error as exc:
            raise LogKnowledgeError("log knowledge submission failed") from exc

    @staticmethod
    def _insert_samples(
        connection: sqlite3.Connection,
        application_id: int,
        samples: list[str] | tuple[str, ...],
    ) -> None:
        now = _utc_now()
        seen: set[str] = set()
        for sample in samples:
            digest = sha256(sample.encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            if len(seen) > 10:
                break
            connection.execute(
                """
                INSERT OR IGNORE INTO log_knowledge_samples (
                    application_id, sample_hash, sample_log, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (application_id, digest, sample, now),
            )

    @staticmethod
    def _add_samples_bounded(
        connection: sqlite3.Connection,
        application_id: int,
        samples: list[str] | tuple[str, ...],
    ) -> None:
        """Add deduplicated review samples inside the caller's transaction."""
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT sample_hash FROM log_knowledge_samples WHERE application_id = ?",
                (application_id,),
            )
        }
        now = _utc_now()
        for sample in samples:
            digest = sha256(sample.encode("utf-8")).hexdigest()
            if digest in existing:
                continue
            if len(existing) >= 10:
                break
            connection.execute(
                """
                INSERT INTO log_knowledge_samples (
                    application_id, sample_hash, sample_log, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (application_id, digest, sample, now),
            )
            existing.add(digest)

    def get_review_detail(self, application_id: int) -> LogKnowledgeReviewDetail:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT recipe_version, structure_hash, structure_tokens_json,
                       format_type, format_spec_json, selection_mode,
                       feature_field, extractor_type, extractor_spec_json,
                       submitter, submission_note, status, created_at,
                       reviewed_at, reviewer, review_reason,
                       replaces_application_id, replaced_by_application_id
                FROM log_knowledge_applications WHERE id = ?
                """,
                (application_id,),
            ).fetchone()
            if row is None:
                raise LogKnowledgeError("log knowledge application not found")
            samples = tuple(
                sample[0]
                for sample in connection.execute(
                    """
                    SELECT sample_log FROM log_knowledge_samples
                    WHERE application_id = ? ORDER BY id
                    """,
                    (application_id,),
                )
            )
        application = LogKnowledgeApplicationInput(
            recipe_version=row[0],
            structure_hash=row[1],
            structure_tokens=tuple(json.loads(row[2])),
            format_type=row[3],
            format_spec=json.loads(row[4]),
            selection_mode=row[5],
            feature_field=row[6],
            extractor_type=row[7],
            extractor_spec=json.loads(row[8]),
            submitter=row[9],
            submission_note=row[10],
        )
        return LogKnowledgeReviewDetail(
            application_id=application_id,
            application=application,
            status=row[11],
            samples=samples,
            created_at=row[12],
            reviewed_at=row[13],
            reviewer=row[14],
            review_reason=row[15],
            replaces_application_id=row[16],
            replaced_by_application_id=row[17],
        )

    def add_samples(
        self, application_id: int, samples: list[str] | tuple[str, ...]
    ) -> None:
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = {
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT sample_hash FROM log_knowledge_samples
                        WHERE application_id = ?
                        """,
                        (application_id,),
                    )
                }
                now = _utc_now()
                for sample in samples:
                    digest = sha256(sample.encode("utf-8")).hexdigest()
                    if digest in existing:
                        continue
                    if len(existing) >= 10:
                        break
                    connection.execute(
                        """
                        INSERT INTO log_knowledge_samples (
                            application_id, sample_hash, sample_log, created_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (application_id, digest, sample, now),
                    )
                    existing.add(digest)
                connection.commit()
        except sqlite3.Error as exc:
            raise LogKnowledgeError("log knowledge sample write failed") from exc

    def approve(
        self, application_id: int, *, reviewer: str, reason: str = ""
    ) -> None:
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT status, structure_hash, selection_mode, feature_field
                    FROM log_knowledge_applications WHERE id = ?
                    """,
                    (application_id,),
                ).fetchone()
                if row is None:
                    raise LogKnowledgeError("log knowledge application not found")
                if row[0] != "pending":
                    raise LogKnowledgeError("only pending log knowledge may be approved")
                active = connection.execute(
                    """
                    SELECT id FROM log_knowledge_applications
                    WHERE status = 'approved' AND structure_hash = ?
                      AND selection_mode = ? AND feature_field = ?
                    """,
                    (row[1], row[2], row[3]),
                ).fetchone()
                if active is not None and not reason.strip():
                    raise LogKnowledgeError(
                        "replacement reason is required for competing approval"
                    )
                now = _utc_now()
                replaces_application_id = None
                if active is not None:
                    replaces_application_id = active[0]
                    connection.execute(
                        """
                        UPDATE log_knowledge_applications
                        SET status = 'rejected', reviewed_at = ?, reviewer = ?,
                            review_reason = ?, replaced_by_application_id = ?
                        WHERE id = ?
                        """,
                        (now, reviewer, reason, application_id, active[0]),
                    )
                    self._after_replacement_update()
                connection.execute(
                    """
                    UPDATE log_knowledge_applications
                    SET status = 'approved', reviewed_at = ?, reviewer = ?,
                        review_reason = ?, replaces_application_id = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        reviewer,
                        reason or None,
                        replaces_application_id,
                        application_id,
                    ),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise LogKnowledgeError("log knowledge approval failed") from exc

    def _after_replacement_update(self) -> None:
        """Test seam after retiring the old approval, before approving the new one."""

    def list_approved_candidates(
        self,
        structure_hash: str,
        selection_mode: str,
        feature_field: str = "",
    ) -> tuple[ApprovedLogKnowledgeCandidate, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, recipe_version, structure_hash, structure_tokens_json,
                       format_type, format_spec_json, selection_mode,
                       feature_field, extractor_type, extractor_spec_json
                FROM log_knowledge_applications
                WHERE status = 'approved' AND structure_hash = ?
                  AND selection_mode = ? AND feature_field = ?
                ORDER BY id
                """,
                (structure_hash, selection_mode, feature_field),
            ).fetchall()
        return tuple(
            ApprovedLogKnowledgeCandidate(
                application_id=row[0],
                recipe_version=row[1],
                structure_hash=row[2],
                structure_tokens=tuple(json.loads(row[3])),
                format_type=row[4],
                format_spec=json.loads(row[5]),
                selection_mode=row[6],
                feature_field=row[7],
                extractor_type=row[8],
                extractor_spec=json.loads(row[9]),
            )
            for row in rows
        )

    def reject(self, application_id: int, *, reviewer: str, reason: str) -> None:
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        if not reason.strip():
            raise ValueError("rejection reason is required")
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    UPDATE log_knowledge_applications
                    SET status = 'rejected', reviewed_at = ?, reviewer = ?,
                        review_reason = ?
                    WHERE id = ? AND status IN ('pending', 'approved')
                    """,
                    (_utc_now(), reviewer, reason, application_id),
                )
                if cursor.rowcount != 1:
                    raise LogKnowledgeError(
                        "only pending or approved log knowledge may be rejected"
                    )
                connection.commit()
        except sqlite3.Error as exc:
            raise LogKnowledgeError("log knowledge rejection failed") from exc

    def delete_rejected(self, application_id: int) -> None:
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    DELETE FROM log_knowledge_applications
                    WHERE id = ? AND status = 'rejected'
                    """,
                    (application_id,),
                )
                if cursor.rowcount != 1:
                    raise LogKnowledgeError(
                        "only rejected log knowledge may be deleted"
                    )
                connection.commit()
        except sqlite3.Error as exc:
            raise LogKnowledgeError("log knowledge deletion failed") from exc

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS log_knowledge_schema_version (
                version INTEGER PRIMARY KEY
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS log_knowledge_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                legacy_source_id INTEGER UNIQUE,
                identity_hash TEXT NOT NULL,
                recipe_version INTEGER NOT NULL CHECK (recipe_version > 0),
                structure_hash TEXT NOT NULL,
                structure_tokens_json TEXT NOT NULL,
                format_type TEXT NOT NULL,
                format_spec_json TEXT NOT NULL,
                selection_mode TEXT NOT NULL
                    CHECK (selection_mode IN ('automatic', 'explicit')),
                feature_field TEXT NOT NULL DEFAULT '',
                extractor_type TEXT NOT NULL
                    CHECK (extractor_type IN ('regex', 'field_path')),
                extractor_spec_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                submitter TEXT NOT NULL,
                submission_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewer TEXT,
                review_reason TEXT,
                use_count INTEGER NOT NULL DEFAULT 0 CHECK (use_count >= 0),
                last_used_at TEXT,
                replaces_application_id INTEGER,
                replaced_by_application_id INTEGER,
                FOREIGN KEY (replaces_application_id)
                    REFERENCES log_knowledge_applications(id) ON DELETE SET NULL,
                FOREIGN KEY (replaced_by_application_id)
                    REFERENCES log_knowledge_applications(id) ON DELETE SET NULL,
                CHECK (
                    (selection_mode = 'automatic' AND feature_field = '')
                    OR
                    (selection_mode = 'explicit'
                        AND length(trim(feature_field)) > 0)
                ),
                CHECK (
                    (status = 'pending' AND reviewed_at IS NULL
                        AND reviewer IS NULL AND review_reason IS NULL)
                    OR
                    (status = 'approved' AND reviewed_at IS NOT NULL
                        AND length(trim(reviewer)) > 0)
                    OR
                    (status = 'rejected' AND reviewed_at IS NOT NULL
                        AND length(trim(reviewer)) > 0
                        AND length(trim(review_reason)) > 0)
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS log_knowledge_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                sample_hash TEXT NOT NULL,
                sample_log TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (application_id)
                    REFERENCES log_knowledge_applications(id) ON DELETE CASCADE,
                UNIQUE (application_id, sample_hash)
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS log_knowledge_one_approved_scope
            ON log_knowledge_applications(
                structure_hash, selection_mode, feature_field
            ) WHERE status = 'approved'
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS log_knowledge_active_identity
            ON log_knowledge_applications(identity_hash)
            WHERE status IN ('pending', 'approved')
            """,
            """
            CREATE TRIGGER IF NOT EXISTS log_knowledge_samples_max_ten
            BEFORE INSERT ON log_knowledge_samples
            WHEN (
                SELECT count(*) FROM log_knowledge_samples
                WHERE application_id = NEW.application_id
            ) >= 10
            BEGIN
                SELECT RAISE(ABORT, 'log knowledge sample limit exceeded');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS log_knowledge_delete_rejected_only
            BEFORE DELETE ON log_knowledge_applications
            WHEN OLD.status <> 'rejected'
            BEGIN
                SELECT RAISE(ABORT, 'only rejected log knowledge may be deleted');
            END
            """,
        )
        for statement in statements:
            connection.execute(statement)
        connection.execute(
            "INSERT OR IGNORE INTO log_knowledge_schema_version(version) VALUES (?)",
            (CURRENT_LOG_KNOWLEDGE_SCHEMA_VERSION,),
        )
        self._migrate_legacy(connection)

    def _migrate_legacy(self, connection: sqlite3.Connection) -> None:
        legacy_exists = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'log_patterns'
            """
        ).fetchone()
        if legacy_exists is None:
            return

        rows = connection.execute(
            """
            SELECT id, fingerprint, format, meta_json, created_at,
                   use_count, last_used_at
            FROM log_patterns ORDER BY id
            """
        ).fetchall()
        for row in rows:
            if connection.execute(
                """
                SELECT 1 FROM log_knowledge_applications
                WHERE legacy_source_id = ?
                """,
                (row[0],),
            ).fetchone():
                continue
            sample_rows = connection.execute(
                """
                SELECT sample_log FROM pattern_samples
                WHERE pattern_id = ? ORDER BY id
                """,
                (row[0],),
            ).fetchall()
            samples = [sample[0] for sample in sample_rows]
            status = "pending"
            migration_reason: str | None = None
            try:
                meta = json.loads(row[3])
                if not isinstance(meta, dict):
                    raise ValueError
            except (json.JSONDecodeError, TypeError, ValueError):
                meta = {}
                status = "rejected"
                migration_reason = "legacy metadata invalid"

            extractor = meta.get("feature_identifier", "")
            selection_mode = meta.get("selection_mode")
            if status == "pending" and selection_mode not in {
                "automatic", "explicit",
            }:
                status = "rejected"
                migration_reason = "legacy_selection_mode_missing"
            feature_field = str(meta.get("feature_field", "") or "")
            if (
                status == "pending"
                and selection_mode == "explicit"
                and not feature_field.strip()
            ):
                status = "rejected"
                migration_reason = "legacy_feature_field_missing"
                feature_field = _LEGACY_MISSING_FEATURE_FIELD
            if status == "pending":
                try:
                    compiled = _re.compile(extractor)
                    if not extractor or not samples:
                        raise ValueError
                except (_re.error, TypeError, ValueError):
                    status = "rejected"
                    migration_reason = "legacy extractor invalid"
                else:
                    if any(compiled.search(sample) is None for sample in samples):
                        status = "rejected"
                        migration_reason = "legacy recipe replay failed"

            if selection_mode != "explicit":
                feature_field = ""
            format_spec = {
                "format_detail": str(
                    meta.get("format_detail", meta.get("log_format_detail", "")) or ""
                )
            }
            extractor_spec = {"pattern": extractor} if extractor else {}
            identity = sha256(
                _stable_json(
                    {
                        "legacy_source_id": row[0],
                        "fingerprint": row[1],
                        "extractor_spec": extractor_spec,
                    }
                ).encode("utf-8")
            ).hexdigest()
            now = _utc_now()
            created_at = row[4] or now
            reviewed_at = now if status == "rejected" else None
            reviewer = "legacy-migration" if status == "rejected" else None
            cursor = connection.execute(
                """
                INSERT INTO log_knowledge_applications (
                    legacy_source_id, identity_hash, recipe_version,
                    structure_hash, structure_tokens_json, format_type,
                    format_spec_json, selection_mode, feature_field,
                    extractor_type, extractor_spec_json, status, submitter,
                    submission_note, created_at, reviewed_at, reviewer,
                    review_reason, use_count, last_used_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, 'regex', ?,
                          ?, 'legacy-migration', '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    row[0],
                    identity,
                    sha256(str(row[1]).encode("utf-8")).hexdigest(),
                    _stable_json((str(row[1]),)),
                    row[2],
                    _stable_json(format_spec),
                    selection_mode if selection_mode in {"automatic", "explicit"} else "automatic",
                    feature_field,
                    _stable_json(extractor_spec),
                    status,
                    created_at,
                    reviewed_at,
                    reviewer,
                    migration_reason,
                    row[5] or 0,
                    row[6],
                ),
            )
            self._insert_samples(connection, int(cursor.lastrowid), samples)
            self._after_legacy_migration_row()

    def _after_legacy_migration_row(self) -> None:
        """Test seam for proving that initialization migration is atomic."""


# ============================================================================
# 指纹脱敏
# ============================================================================

# IP 地址 (IPv4 简单匹配)
_IP_RE = _re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)
# 时间戳多种格式
_TIME_RE = _re.compile(
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}[T ]\d{1,2}:\d{2}:\d{2}(?:\.\d+)?"
    r"|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b"  # May 12 16:48:10
    r"|"
    r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b"  # 16:48:10
)
# 纯数字序列 (至少 3 位, 防止误杀短数字如 port, status)
_NUMBER_RE = _re.compile(r"\b\d{4,}\b")

def generate_log_fingerprint(log_line: str) -> str:
    """
    对单行日志进行指纹脱敏，保留结构骨架。

    Args:
        log_line: 一行原始日志

    Returns:
        脱敏后的指纹字符串
    """
    # 1. 替换时间戳
    line = _TIME_RE.sub("{time}", log_line)
    # 2. 替换 IP
    line = _IP_RE.sub("{ip}", line)
    # 3. 替换长数字序列
    line = _NUMBER_RE.sub("{n}", line)

    # 4. 保留非字母数字字符 (分隔符结构)，字母转小写
    line = line.lower()

    return line


def generate_fingerprint_from_fields(pattern_info: dict) -> str:
    """
    从字段特征信息生成指纹（不依赖原始日志行）。

    Args:
        pattern_info: classify_log_features 输出，包含 fields 列表

    Returns:
        指纹字符串（字段名序列 + 类型序列）
    """
    fields = pattern_info.get("fields", [])
    if not fields:
        return ""

    field_names = [f.get("field_name", "?") for f in fields]
    field_types = [f.get("field_type", "string") for f in fields]
    fmt = pattern_info.get("format", "unknown")

    # 指纹: format|field1:type1,field2:type2,...
    finger = f"{fmt}|" + ",".join(
        f"{n}:{t}" for n, t in zip(field_names, field_types)
    )
    return finger


def generate_structured_fingerprint(
    classify_result: dict,
    format_detail: str = "",
    feature_field: str = "",
) -> str:
    """
    基于 classify_log_features 输出的语义骨架生成结构化指纹。
    
    指纹 = format_detail | feature_field | feature_identifier_clean
    
    对日志增删字段不敏感——只要核心正则骨架不变，指纹就不变。
    
    feature_identifier_clean 处理：
    - 将 Group 2（值捕获）改为通用匹配，使同类日志指纹一致
    - 归一化转义字符统一用小写 (\\s, \\w, \\d ...)
    
    Args:
        classify_result: classify_log_features 的输出 dict
        format_detail: 格式详情（"日志头+JSON" / "JSON" / "KV" ...）
        feature_field: 业务分类字段名
        
    Returns:
        结构化指纹字符串
    """
    fd = format_detail or classify_result.get("format_detail", "") or classify_result.get("log_format", "")
    ff = feature_field or classify_result.get("feature_field", "")
    fi = classify_result.get("feature_identifier", "")
    
    # 归一化 feature_identifier：去掉尾部精确值捕获组，保留结构骨架
    # 策略：提取 Group 1 部分（去掉日志头后的主体），保留其正则结构
    fi_clean = _normalize_feature_identifier(fi)
    
    return f"{fd}|{ff}|{fi_clean}"


def _normalize_feature_identifier(feature_identifier: str) -> str:
    """
    归一化 feature_identifier，去除值相关的精确匹配，保留结构骨架。
    
    处理步骤：
    1. 将 Group 2（字段值捕获组）内容泛化
    2. 统一转义字符为小写
    3. 统一空格
    
    Args:
        feature_identifier: 双捕获组正则表达式
        
    Returns:
        归一化后的正则骨架
    """
    if not feature_identifier:
        return ""
    
    fi = feature_identifier.strip()
    
    # 将大写的转义符统一为小写
    fi = _re.sub(r'\\([SWDNswdn])', lambda m: f'\\{m.group(1).lower()}', fi)
    
    # 将捕获组中的精确字符串值泛化（如 "dac_dga_log" → "[^\"]*"）
    # 匹配捕获组内的字面量字符串
    fi = _re.sub(r'"([^"\\]*(?:\\.[^"\\]*)*)"', r'"[^"]*"', fi)
    
    # 标准化空白（去掉多余空格）
    fi = _re.sub(r'\s+', '', fi)
    
    return fi


# ============================================================================
# SQLite 存储
# ============================================================================


def _get_connection() -> sqlite3.Connection:
    """Compatibility connection to the repository-owned SQLite database."""
    return LogKnowledgeRepository().connect()


def store_log_knowledge(
    fingerprint: str,
    format_type: str,
    meta: dict,
    sample_logs: list[str] | None = None,
) -> int | None:
    """Compatibility entry that creates a pending repository application."""
    selection_mode = meta.get("selection_mode", "automatic")
    if selection_mode not in {"automatic", "explicit"}:
        selection_mode = "automatic"
    feature_field = str(meta.get("feature_field", "") or "")
    if selection_mode != "explicit":
        feature_field = ""
    feature_identifier = str(meta.get("feature_identifier", "") or "")
    analysis = meta.get("analysis") if isinstance(meta.get("analysis"), dict) else {}
    format_spec = {
        "format_detail": str(
            meta.get("log_format_detail", meta.get("format_detail", "")) or ""
        ),
        "delimit": str(analysis.get("delimit", "") or ""),
        "tab": str(analysis.get("tab", "") or ""),
    }
    application = LogKnowledgeApplicationInput(
        recipe_version=1,
        structure_hash=sha256(fingerprint.encode("utf-8")).hexdigest(),
        structure_tokens=tuple(fingerprint.split("|")),
        format_type=format_type,
        format_spec=format_spec,
        selection_mode=selection_mode,
        feature_field=feature_field,
        extractor_type="regex",
        extractor_spec={"pattern": feature_identifier},
        submitter="classification-runtime",
    )
    try:
        repository = LogKnowledgeRepository()
        try:
            return repository.create_application(application, samples=sample_logs or [])
        except LogKnowledgeError:
            application_id = repository.get_active_application_id(application)
            if application_id is None:
                raise
            repository.add_samples(application_id, sample_logs or [])
            return application_id
    except Exception as exc:
        logger.error("[STORE] log knowledge application write failed: %s", type(exc).__name__)
        return None


def retrieve_log_knowledge(
    query_text: str,
    top_k: int = 5,
    threshold: float = 0.85,
) -> list[dict]:
    """Retained compatibility seam; ranking/replay is intentionally deferred."""
    del query_text, top_k, threshold
    return []


def auto_match_log(logs_str: str, sample_size: int = 3) -> dict | None:
    """Retained compatibility seam until candidate ranking is implemented."""
    del logs_str, sample_size
    return None


# ============================================================================
# 增量更新
# ============================================================================


def update_log_pattern(
    pattern_id: int,
    meta: dict | None = None,
    sample_logs: list[str] | None = None,
) -> bool:
    """Compatibility update limited to adding bounded review samples."""
    if meta is not None:
        logger.warning("[UPDATE] recipe metadata is immutable; submit a new application")
        return False
    try:
        if sample_logs is not None:
            LogKnowledgeRepository().add_samples(pattern_id, sample_logs)
        return True
    except Exception as exc:
        logger.error("[UPDATE] log knowledge sample update failed: %s", type(exc).__name__)
        return False


def list_all_patterns() -> list[dict]:
    """List review applications without exposing raw samples."""
    try:
        repository = LogKnowledgeRepository()
        with repository.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, structure_hash, format_type, status, use_count,
                       created_at, last_used_at
                FROM log_knowledge_applications
                ORDER BY id
                """
            ).fetchall()
        return [
            {
                "pattern_id": row[0],
                "fingerprint": row[1],
                "format": row[2],
                "status": row[3],
                "use_count": row[4],
                "created_at": row[5],
                "last_used_at": row[6],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.error("[LIST] log knowledge listing failed: %s", type(exc).__name__)
        return []


def delete_pattern(pattern_id: int) -> bool:
    """Compatibility deletion restricted to rejected applications."""
    try:
        LogKnowledgeRepository().delete_rejected(pattern_id)
        return True
    except Exception as exc:
        logger.error("[DELETE] log knowledge deletion failed: %s", type(exc).__name__)
        return False
