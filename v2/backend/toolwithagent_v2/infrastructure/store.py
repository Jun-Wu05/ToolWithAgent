"""Transactional V2 storage, queue and file ingest operations."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os
import secrets
import time

from .db import connect, migrate
from toolwithagent_v2.settings import Settings


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid4())


def object_dict(row):
    return dict(row) if row is not None else None


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir
        self.path = self.root / "v2.sqlite3"
        migrate(self.path)
        (self.root / "uploads").mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.root / "staging").mkdir(parents=True, exist_ok=True)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            for user_id, name, role in (("dev-user", "演示用户", "user"), ("dev-other", "开发者", "developer"), ("dev-admin", "管理员", "admin")):
                db.execute("INSERT OR IGNORE INTO users(id,display_name,role,is_active,created_at) VALUES(?,?,?,?,?)", (user_id, name, role, 1, now()))
            db.commit()
        self.reconcile_blobs()

    def users(self):
        with connect(self.path) as db:
            return [dict(r) for r in db.execute("SELECT id,display_name,role FROM users WHERE is_active=1 ORDER BY id")]

    def user(self, user_id):
        with connect(self.path) as db:
            return object_dict(db.execute("SELECT id,display_name,role FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone())

    def owns(self, db, conversation_id, owner_id):
        row = db.execute("SELECT * FROM conversations WHERE id=? AND owner_id=? AND archived_at IS NULL", (conversation_id, owner_id)).fetchone()
        if row is None:
            raise LookupError("conversation_not_found")
        return row

    def list_conversations(self, owner_id):
        with connect(self.path) as db:
            return [dict(r) for r in db.execute("SELECT id,title,created_at,updated_at FROM conversations WHERE owner_id=? AND archived_at IS NULL ORDER BY updated_at DESC,id DESC", (owner_id,))]

    def create_conversation(self, owner_id, title):
        conversation_id, timestamp = uid(), now()
        title = (title or "新会话").strip()[:160] or "新会话"
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO conversations(id,owner_id,title,created_at,updated_at) VALUES(?,?,?,?,?)", (conversation_id, owner_id, title, timestamp, timestamp))
            self._event(db, conversation_id, "conversation_created", "conversation", conversation_id, {"title": title})
            db.commit()
        return {"id": conversation_id, "title": title, "created_at": timestamp, "updated_at": timestamp}

    def get_conversation(self, owner_id, conversation_id):
        with connect(self.path) as db:
            row = self.owns(db, conversation_id, owner_id)
            messages = [dict(r) for r in db.execute("SELECT id,actor,kind,content_json,created_at FROM messages WHERE conversation_id=? ORDER BY created_at,id", (conversation_id,))]
            for m in messages:
                m["content"] = json.loads(m.pop("content_json"))["text"]
            files = [self._file(r) for r in db.execute("SELECT * FROM files WHERE conversation_id=? ORDER BY created_at,id", (conversation_id,))]
            runs = [self._run(r) for r in db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE t.conversation_id=? ORDER BY r.queued_at,r.id", (conversation_id,))]
            return {"id": row["id"], "title": row["title"], "created_at": row["created_at"], "updated_at": row["updated_at"], "messages": messages, "files": files, "runs": runs, "artifacts": self._artifacts(db, conversation_id)}

    def create_message(self, owner_id, conversation_id, content, idempotency_key=None):
        content = content.strip()
        if not content or len(content) > 20000:
            raise ValueError("invalid_message")
        message_id, timestamp = uid(), now()
        request_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.owns(db, conversation_id, owner_id)
            if idempotency_key:
                receipt = db.execute("SELECT request_sha256,result_json FROM idempotency_receipts WHERE principal_id=? AND operation_scope=? AND key=?", (owner_id, "message:" + conversation_id, idempotency_key)).fetchone()
                if receipt:
                    if receipt["request_sha256"] != request_hash:
                        raise ValueError("idempotency_key_reused")
                    return json.loads(receipt["result_json"])
            db.execute("INSERT INTO messages(id,conversation_id,actor,kind,content_json,created_at) VALUES(?,?,?,?,?,?)", (message_id, conversation_id, "user", "text", json.dumps({"text": content}, ensure_ascii=False), timestamp))
            db.execute("UPDATE conversations SET updated_at=?,revision=revision+1 WHERE id=?", (timestamp, conversation_id))
            self._event(db, conversation_id, "message_created", "message", message_id, {"actor": "user"})
            result = {"id": message_id, "actor": "user", "kind": "text", "content": content, "created_at": timestamp}
            if idempotency_key:
                db.execute("INSERT INTO idempotency_receipts(id,principal_id,operation_scope,key,request_sha256,status,result_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid(), owner_id, "message:" + conversation_id, idempotency_key, request_hash, "completed", json.dumps(result, ensure_ascii=False), timestamp))
            db.commit()
        return result

    def upload(self, owner_id, conversation_id, upload, idempotency_key=None):
        with connect(self.path) as db:
            self.owns(db, conversation_id, owner_id)
        original = Path(upload.filename or "upload").name[:255]
        suffix = Path(original).suffix.lower()
        media = {".csv":"text/csv", ".txt":"text/plain", ".log":"text/plain", ".json":"application/json", ".jsonl":"application/x-ndjson", ".xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".b64":"text/plain"}.get(suffix)
        if media is None:
            raise ValueError("unsupported_file_type")
        stage = self.root / "uploads" / (uid() + ".stage")
        digest = hashlib.sha256()
        size = 0
        try:
            with stage.open("wb") as output:
                while chunk := upload.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise ValueError("file_too_large")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size == 0:
                raise ValueError("empty_file")
            sha = digest.hexdigest()
            request_hash = hashlib.sha256(json.dumps([conversation_id, original, media, sha], separators=(",", ":")).encode()).hexdigest()
            key = f"uploads/{sha[:2]}/{sha}"
            final = self.root / key
            final.parent.mkdir(parents=True, exist_ok=True)
            if not final.exists():
                os.replace(stage, final)
            else:
                stage.unlink()
            file_id, task_id, run_id, timestamp = uid(), uid(), uid(), now()
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                self.owns(db, conversation_id, owner_id)
                if idempotency_key:
                    receipt = db.execute("SELECT request_sha256,result_json FROM idempotency_receipts WHERE principal_id=? AND operation_scope=? AND key=?", (owner_id, "upload:" + conversation_id, idempotency_key)).fetchone()
                    if receipt:
                        if receipt["request_sha256"] != request_hash:
                            raise ValueError("idempotency_key_reused")
                        return json.loads(receipt["result_json"])
                db.execute("INSERT INTO files(id,owner_id,conversation_id,original_name,media_type,size,sha256,storage_key,parse_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (file_id, owner_id, conversation_id, original, media, size, sha, key, "queued", timestamp, timestamp))
                db.execute("INSERT INTO tasks(id,conversation_id,owner_id,type,status,current_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (task_id, conversation_id, owner_id, "file_ingest", "queued", run_id, timestamp, timestamp))
                db.execute("INSERT INTO runs(id,task_id,attempt,status,input_snapshot_json,queued_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (run_id, task_id, 1, "queued", json.dumps({"file_id": file_id, "sha256": sha, "storage_key": key, "media_type": media}, separators=(",", ":")), timestamp, timestamp, timestamp))
                db.execute("UPDATE conversations SET updated_at=?,revision=revision+1 WHERE id=?", (timestamp, conversation_id))
                self._run_event(db, run_id, "run_queued", "queued")
                self._event(db, conversation_id, "file_uploaded", "file", file_id, {"file_id": file_id, "name": original})
                self._event(db, conversation_id, "run_queued", "run", run_id, {"run_id": run_id, "status": "queued"})
                result = {"file": {"id": file_id, "name": original, "media_type": media, "size": size, "sha256": sha, "parse_status": "queued", "created_at": timestamp}, "task": {"id": task_id, "status": "queued"}, "run": {"id": run_id, "status": "queued"}}
                if idempotency_key:
                    db.execute("INSERT INTO idempotency_receipts(id,principal_id,operation_scope,key,request_sha256,status,result_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid(), owner_id, "upload:" + conversation_id, idempotency_key, request_hash, "completed", json.dumps(result, ensure_ascii=False), timestamp))
                db.commit()
            return result
        finally:
            stage.unlink(missing_ok=True)

    def _enqueue_task(self, db, owner_id, conversation_id, kind, snapshot):
        timestamp = now()
        task_id, run_id = uid(), uid()
        db.execute("INSERT INTO tasks(id,conversation_id,owner_id,type,status,current_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (task_id, conversation_id, owner_id, kind, "queued", run_id, timestamp, timestamp))
        db.execute("INSERT INTO runs(id,task_id,attempt,status,input_snapshot_json,queued_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (run_id, task_id, 1, "queued", json.dumps(snapshot, ensure_ascii=False, sort_keys=True), timestamp, timestamp, timestamp))
        self._run_event(db, run_id, "run_queued", "queued")
        self._event(db, conversation_id, "run_queued", "run", run_id, {"run_id": run_id, "status": "queued"})
        return {"task": {"id": task_id, "status": "queued"}, "run": {"id": run_id, "status": "queued"}}

    def enqueue_log_parse(self, owner_id, conversation_id, file_id, feature_field=None):
        if feature_field is not None:
            feature_field = feature_field.strip()
            if not feature_field or len(feature_field) > 160:
                raise ValueError("invalid_feature_field")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.owns(db, conversation_id, owner_id)
            file = db.execute("SELECT * FROM files WHERE id=? AND conversation_id=? AND owner_id=?", (file_id, conversation_id, owner_id)).fetchone()
            if file is None:
                raise LookupError("file_not_found")
            if file["parse_status"] != "succeeded":
                raise ValueError("file_not_validated")
            if file["media_type"] not in {"text/plain", "application/json", "application/x-ndjson", "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
                raise ValueError("unsupported_log_type")
            snapshot = {key: file[key] for key in ("sha256", "storage_key", "media_type")}
            snapshot.update({"file_id": file_id, "feature_field": feature_field})
            result = self._enqueue_task(db, owner_id, conversation_id, "log_parse", snapshot)
            db.commit()
            return result

    def enqueue_log_knowledge(self, owner_id, artifact_id):
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            artifact = db.execute("""SELECT a.*,t.owner_id,r.input_snapshot_json
                FROM artifacts a JOIN tasks t ON t.id=a.task_id JOIN runs r ON r.id=a.run_id
                WHERE a.id=? AND a.kind='log_classification' AND a.status='published' AND t.owner_id=?""",
                (artifact_id, owner_id)).fetchone()
            if artifact is None:
                raise LookupError("artifact_not_found")
            metadata = json.loads(artifact["metadata_json"])
            if not metadata.get("submission_eligible"):
                raise ValueError("submission_not_eligible")
            latest_file = db.execute("SELECT id FROM files WHERE conversation_id=? AND parse_status='succeeded' ORDER BY created_at DESC,id DESC LIMIT 1", (artifact["conversation_id"],)).fetchone()
            latest_artifact = db.execute("SELECT id FROM artifacts WHERE conversation_id=? AND kind='log_classification' AND status='published' ORDER BY created_at DESC,id DESC LIMIT 1", (artifact["conversation_id"],)).fetchone()
            if (not latest_file or latest_file["id"] != json.loads(artifact["input_snapshot_json"])["file_id"]
                or not latest_artifact or latest_artifact["id"] != artifact_id):
                raise ValueError("submission_stale")
            source = json.loads(artifact["input_snapshot_json"])
            latest = db.execute("""SELECT id,status FROM runs WHERE task_id IN
                (SELECT id FROM tasks WHERE type='log_knowledge_submit' AND conversation_id=?)
                AND json_extract(input_snapshot_json,'$.source_artifact_id')=?
                ORDER BY created_at DESC LIMIT 1""", (artifact["conversation_id"], artifact_id)).fetchone()
            if latest and latest["status"] in ("queued", "running", "waiting_confirmation"):
                raise ValueError("task_has_active_run")
            result = self._enqueue_task(db, owner_id, artifact["conversation_id"], "log_knowledge_submit",
                {**source, "source_artifact_id": artifact_id, "source_sha256": artifact["sha256"],
                 "source_storage_key": artifact["storage_key"]})
            db.commit()
            return result

    def _submission_is_current_db(self, db, claim):
        snapshot = claim["input"]
        file = db.execute("SELECT id FROM files WHERE conversation_id=? AND parse_status='succeeded' ORDER BY created_at DESC,id DESC LIMIT 1",
                          (claim["conversation_id"],)).fetchone()
        artifact = db.execute("SELECT id FROM artifacts WHERE conversation_id=? AND kind='log_classification' AND status='published' ORDER BY created_at DESC,id DESC LIMIT 1",
                              (claim["conversation_id"],)).fetchone()
        return bool(file and artifact and file["id"] == snapshot["file_id"]
                    and artifact["id"] == snapshot["source_artifact_id"])

    def read_classification(self, claim):
        snapshot = claim["input"]
        with connect(self.path) as db:
            artifact = db.execute("""SELECT a.* FROM artifacts a WHERE a.id=? AND a.conversation_id=?
                AND a.kind='log_classification' AND a.status='published'""",
                (snapshot["source_artifact_id"], claim["conversation_id"])).fetchone()
            if artifact is None or artifact["sha256"] != snapshot["source_sha256"] or artifact["storage_key"] != snapshot["source_storage_key"]:
                raise ValueError("submission_stale")
        key = artifact["storage_key"]
        if not key.startswith("artifacts/") or ".." in key.split("/"):
            raise ValueError("submission_stale")
        path = (self.root / key).resolve()
        if not path.is_relative_to((self.root / "artifacts").resolve()):
            raise ValueError("submission_stale")
        try:
            content = path.read_bytes()
        except OSError:
            raise ValueError("submission_stale") from None
        if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
            raise ValueError("submission_stale")
        return json.loads(content)

    def submission_is_current(self, claim):
        with connect(self.path) as db:
            return self._submission_is_current_db(db, claim)

    def _artifacts(self, db, conversation_id):
        rows = db.execute("""SELECT a.*,r.input_snapshot_json FROM artifacts a
            JOIN runs r ON r.id=a.run_id WHERE a.conversation_id=?
            AND a.kind='log_classification' AND a.status='published' ORDER BY a.created_at,a.id""",
            (conversation_id,)).fetchall()
        result = []
        latest_file = db.execute("SELECT id FROM files WHERE conversation_id=? AND parse_status='succeeded' ORDER BY created_at DESC,id DESC LIMIT 1", (conversation_id,)).fetchone()
        latest_artifact_id = rows[-1]["id"] if rows else None
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            latest = db.execute("""SELECT r.status,r.error_code,a.metadata_json FROM runs r
                JOIN tasks t ON t.id=r.task_id LEFT JOIN artifacts a ON a.run_id=r.id
                WHERE t.type='log_knowledge_submit' AND
                json_extract(r.input_snapshot_json,'$.source_artifact_id')=?
                ORDER BY r.created_at DESC LIMIT 1""", (row["id"],)).fetchone()
            status = None
            application_id = None
            if latest:
                if latest["metadata_json"]:
                    terminal = json.loads(latest["metadata_json"])
                    status = terminal.get("submission_status")
                    application_id = terminal.get("application_id")
                elif latest["error_code"] and latest["error_code"].startswith("log_knowledge_submission_"):
                    status = latest["error_code"].removeprefix("log_knowledge_submission_")
                else:
                    status = latest["status"]
            result.append({"id": row["id"], "run_id": row["run_id"],
                "file_id": json.loads(row["input_snapshot_json"])["file_id"],
                "kind": row["kind"], "status": row["status"], "summary": metadata.get("summary", {}),
                "submission_eligible": bool(metadata.get("submission_eligible")) and bool(latest_file) and latest_file["id"] == json.loads(row["input_snapshot_json"])["file_id"] and row["id"] == latest_artifact_id,
                "submission_status": status, "application_id": application_id,
                "created_at": row["created_at"]})
        return result

    def _file(self, row):
        return {"id": row["id"], "name": row["original_name"], "media_type": row["media_type"], "size": row["size"], "sha256": row["sha256"], "parse_status": row["parse_status"], "created_at": row["created_at"]}

    def _run(self, row):
        return {"id": row["id"], "task_id": row["task_id"], "kind": row["task_type"], "file_id": json.loads(row["input_snapshot_json"]).get("file_id"), "status": row["status"], "attempt": row["attempt"], "queued_at": row["queued_at"], "started_at": row["started_at"], "finished_at": row["finished_at"], "error_code": row["error_code"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get_run(self, owner_id, run_id):
        with connect(self.path) as db:
            row = db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=? AND t.owner_id=?", (run_id, owner_id)).fetchone()
            if row is None:
                raise LookupError("run_not_found")
            return self._run(row)

    def events(self, owner_id, conversation_id, after):
        with connect(self.path) as db:
            self.owns(db, conversation_id, owner_id)
            return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in db.execute("SELECT sequence,event_type,resource_type,resource_id,payload_json FROM conversation_events WHERE conversation_id=? AND sequence>? ORDER BY sequence", (conversation_id, after))]

    def _event(self, db, conversation_id, event_type, resource_type, resource_id, payload):
        seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM conversation_events WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
        db.execute("INSERT INTO conversation_events(id,conversation_id,sequence,event_type,resource_type,resource_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid(), conversation_id, seq, event_type, resource_type, resource_id, json.dumps(payload, ensure_ascii=False), now()))

    def _run_event(self, db, run_id, event_type, status):
        seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM run_events WHERE run_id=?", (run_id,)).fetchone()[0]
        db.execute("INSERT INTO run_events(id,run_id,sequence,scope_type,scope_id,event_type,status,summary_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (uid(), run_id, seq, "run", run_id, event_type, status, "{}", now()))

    def claim(self, worker_id, lease_seconds=30):
        timestamp = now()
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT * FROM worker_leases WHERE id='v2-primary'").fetchone()
            if lease["owner_id"] != worker_id and lease["lease_expires_at"] and lease["lease_expires_at"] > timestamp:
                db.commit()
                return None
            expired = not lease["lease_expires_at"] or lease["lease_expires_at"] <= timestamp
            epoch = lease["epoch"] + (1 if lease["owner_id"] != worker_id or expired else 0)
            db.execute("UPDATE worker_leases SET owner_id=?,lease_expires_at=?,epoch=? WHERE id='v2-primary'", (worker_id, deadline, epoch))
            stale = db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.status='running' AND (r.lease_expires_at<=? OR r.leader_epoch<>?)", (timestamp, epoch)).fetchall()
            for abandoned in stale:
                db.execute("UPDATE runs SET status='failed',error_code='worker_lost',finished_at=?,updated_at=?,lease_owner=NULL,lease_expires_at=NULL,fence_token=NULL,revision=revision+1 WHERE id=? AND status='running'", (timestamp, timestamp, abandoned["id"]))
                db.execute("UPDATE tasks SET status='failed',updated_at=?,revision=revision+1 WHERE id=?", (timestamp, abandoned["task_id"]))
                snapshot = json.loads(abandoned["input_snapshot_json"])
                if abandoned["task_type"] == "file_ingest":
                    db.execute("UPDATE files SET parse_status='failed',updated_at=? WHERE id=?", (timestamp, snapshot.get("file_id", "")))
                self._run_event(db, abandoned["id"], "run_failed", "failed")
                self._event(db, abandoned["conversation_id"], "run_failed", "run", abandoned["id"], {"run_id": abandoned["id"], "status": "failed", "error_code": "worker_lost"})
            if db.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone():
                db.commit()
                return None
            row = db.execute("SELECT r.*,t.conversation_id,t.owner_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.status='queued' ORDER BY r.queued_at,r.id LIMIT 1").fetchone()
            if row is None:
                db.commit()
                return None
            fence = uid()
            db.execute("UPDATE runs SET status='running',started_at=?,updated_at=?,lease_owner=?,lease_expires_at=?,leader_epoch=?,fence_token=?,revision=revision+1 WHERE id=?", (timestamp, timestamp, worker_id, deadline, epoch, fence, row["id"]))
            db.execute("UPDATE tasks SET status='running',updated_at=?,revision=revision+1 WHERE id=?", (timestamp, row["task_id"]))
            self._run_event(db, row["id"], "run_started", "running")
            self._event(db, row["conversation_id"], "run_started", "run", row["id"], {"run_id": row["id"], "status": "running"})
            db.commit()
            return {"id": row["id"], "task_id": row["task_id"], "conversation_id": row["conversation_id"], "input": json.loads(row["input_snapshot_json"]), "task_type": row["task_type"], "owner_id": row["owner_id"], "fence": fence, "epoch": epoch}

    def renew(self, worker_id, claim, lease_seconds=30):
        timestamp = now()
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT owner_id,epoch,lease_expires_at FROM worker_leases WHERE id='v2-primary'").fetchone()
            run = db.execute("SELECT status,lease_owner,fence_token,leader_epoch,lease_expires_at FROM runs WHERE id=?", (claim["id"],)).fetchone()
            if (lease["owner_id"] != worker_id or lease["epoch"] != claim["epoch"] or lease["lease_expires_at"] <= timestamp or run is None or run["status"] != "running" or run["lease_owner"] != worker_id or run["fence_token"] != claim["fence"] or run["leader_epoch"] != claim["epoch"] or run["lease_expires_at"] <= timestamp):
                db.rollback()
                return False
            db.execute("UPDATE worker_leases SET lease_expires_at=? WHERE id='v2-primary'", (deadline,))
            db.execute("UPDATE runs SET lease_expires_at=? WHERE id=?", (deadline, claim["id"]))
            db.commit()
            return True

    def finish(self, worker_id, claim, error_code=None, message=None):
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._valid_claim(db, worker_id, claim)
            if row is None:
                db.rollback()
                return False
            if message:
                self._assistant_message(db, row["conversation_id"], message)
            self._record_state(db, row, "failed" if error_code else "succeeded", error_code)
            db.commit()
            return True

    def _assistant_message(self, db, conversation_id, message):
        message_id = uid()
        db.execute("INSERT INTO messages(id,conversation_id,actor,kind,content_json,created_at) VALUES(?,?,?,?,?,?)",
                   (message_id, conversation_id, "assistant", "text", json.dumps({"text": message}, ensure_ascii=False), now()))
        self._event(db, conversation_id, "message_created", "message", message_id, {"actor": "assistant"})

    def _owned_run(self, db, owner_id, run_id):
        row = db.execute("SELECT r.*,t.owner_id,t.conversation_id,t.current_run_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=? AND t.owner_id=?", (run_id, owner_id)).fetchone()
        if row is None:
            raise LookupError("run_not_found")
        return row

    def _record_state(self, db, row, status, error_code=None):
        timestamp = now()
        terminal = status in ("succeeded", "failed", "cancelled")
        db.execute("UPDATE runs SET status=?,error_code=?,updated_at=?,finished_at=CASE WHEN ? THEN ? ELSE finished_at END,lease_owner=NULL,lease_expires_at=NULL,fence_token=NULL,revision=revision+1 WHERE id=?",
                   (status, error_code, timestamp, terminal, timestamp, row["id"]))
        db.execute("UPDATE tasks SET status=?,updated_at=?,revision=revision+1 WHERE id=? AND current_run_id=?",
                   (status, timestamp, row["task_id"], row["id"]))
        if row["input_snapshot_json"]:
            snapshot = json.loads(row["input_snapshot_json"])
            if row["task_type"] == "file_ingest" and snapshot.get("file_id"):
                db.execute("UPDATE files SET parse_status=?,updated_at=? WHERE id=?", (status, timestamp, snapshot["file_id"]))
        self._run_event(db, row["id"], "run_" + status, status)
        self._event(db, row["conversation_id"], "run_" + status, "run", row["id"],
                    {"run_id": row["id"], "status": status, "error_code": error_code})

    def retry(self, owner_id, run_id, idempotency_key=None):
        timestamp = now()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            source = self._owned_run(db, owner_id, run_id)
            scope = "retry:" + run_id
            if idempotency_key:
                receipt = db.execute("SELECT result_json FROM idempotency_receipts WHERE principal_id=? AND operation_scope=? AND key=?",
                                     (owner_id, scope, idempotency_key)).fetchone()
                if receipt:
                    return json.loads(receipt["result_json"])
            if source["status"] not in ("succeeded", "failed", "cancelled"):
                raise ValueError("run_not_retryable")
            current = db.execute("SELECT status FROM runs WHERE id=?", (source["current_run_id"],)).fetchone()
            if current and current["status"] not in ("succeeded", "failed", "cancelled"):
                raise ValueError("task_has_active_run")
            attempt = db.execute("SELECT COALESCE(MAX(attempt),0)+1 FROM runs WHERE task_id=?", (source["task_id"],)).fetchone()[0]
            new_id = uid()
            db.execute("""INSERT INTO runs(id,task_id,attempt,status,input_snapshot_json,provider_config_revision,prompt_version,standard_field_version,queued_at,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                       (new_id, source["task_id"], attempt, "queued", source["input_snapshot_json"],
                        source["provider_config_revision"], source["prompt_version"], source["standard_field_version"],
                        timestamp, timestamp, timestamp))
            db.execute("UPDATE tasks SET status='queued',current_run_id=?,updated_at=?,revision=revision+1 WHERE id=?",
                       (new_id, timestamp, source["task_id"]))
            snapshot = json.loads(source["input_snapshot_json"])
            if source["task_type"] == "file_ingest" and snapshot.get("file_id"):
                db.execute("UPDATE files SET parse_status='queued',updated_at=? WHERE id=?", (timestamp, snapshot["file_id"]))
            self._run_event(db, new_id, "run_queued", "queued")
            self._event(db, source["conversation_id"], "run_queued", "run", new_id,
                        {"run_id": new_id, "status": "queued", "attempt": attempt, "source_run_id": run_id})
            result = {"id": new_id, "task_id": source["task_id"], "status": "queued", "attempt": attempt}
            if idempotency_key:
                db.execute("INSERT INTO idempotency_receipts(id,principal_id,operation_scope,key,request_sha256,status,result_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (uid(), owner_id, scope, idempotency_key, hashlib.sha256(run_id.encode()).hexdigest(), "completed", json.dumps(result), timestamp))
            db.commit()
            return result

    def issue_cancel_token(self, owner_id, run_id):
        token = secrets.token_urlsafe(32)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_run(db, owner_id, run_id)
            if row["current_run_id"] != run_id or row["status"] not in ("queued", "running", "waiting_confirmation"):
                raise ValueError("run_not_cancellable")
            db.execute("UPDATE confirmations SET status='superseded',rotated_at=? WHERE run_id=? AND kind='cancel' AND status='pending'", (now(), run_id))
            db.execute("INSERT INTO confirmations(id,task_id,run_id,checkpoint_id,checkpoint_revision,token_sha256,kind,payload_json,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (uid(), row["task_id"], run_id, "", row["revision"], hashlib.sha256(token.encode()).hexdigest(),
                        "cancel", "{}", "pending", (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(), now()))
            db.commit()
        return {"token": token, "run_id": run_id, "revision": row["revision"]}

    def cancel(self, owner_id, run_id, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_run(db, owner_id, run_id)
            if row["current_run_id"] != run_id or row["status"] not in ("queued", "running", "waiting_confirmation"):
                raise ValueError("run_not_cancellable")
            confirmation = db.execute("SELECT * FROM confirmations WHERE run_id=? AND kind='cancel' AND status='pending' AND token_sha256=? ORDER BY created_at DESC LIMIT 1", (run_id, digest)).fetchone()
            if confirmation is None or confirmation["expires_at"] <= now() or confirmation["checkpoint_revision"] != row["revision"]:
                raise ValueError("invalid_confirmation_token")
            db.execute("UPDATE confirmations SET status='consumed',consumed_at=? WHERE id=?", (now(), confirmation["id"]))
            db.execute("UPDATE confirmations SET status='superseded',rotated_at=? WHERE run_id=? AND kind='resume' AND status='pending'", (now(), run_id))
            if row["status"] != "queued":
                self._record_state(db, row, "cancelling")
            self._record_state(db, row, "cancelled")
            db.commit()
            return {"id": run_id, "status": "cancelled"}

    def force_stop(self, admin_id, run_id, reason):
        if not reason or not reason.strip() or len(reason.strip()) > 1000:
            raise ValueError("reason_required")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT r.*,t.conversation_id,t.current_run_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?", (run_id,)).fetchone()
            if row is None:
                raise LookupError("run_not_found")
            if row["current_run_id"] != run_id or row["status"] not in ("queued", "running", "waiting_confirmation"):
                raise ValueError("run_not_stoppable")
            db.execute("UPDATE confirmations SET status='superseded',rotated_at=? WHERE run_id=? AND status='pending'", (now(), run_id))
            if row["status"] != "queued":
                self._record_state(db, row, "cancelling", "force_stopped")
            self._record_state(db, row, "cancelled", "force_stopped")
            db.execute("INSERT INTO audit_events(id,actor_id,action,target_type,target_id,created_at,reason) VALUES(?,?,?,?,?,?,?)",
                       (uid(), admin_id, "force_stop", "run", run_id, now(), reason.strip()))
            db.commit()
            return {"id": run_id, "status": "cancelled", "error_code": "force_stopped"}

    def _valid_claim(self, db, worker_id, claim):
        timestamp = now()
        lease = db.execute("SELECT * FROM worker_leases WHERE id='v2-primary'").fetchone()
        row = db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?", (claim["id"],)).fetchone()
        if (row is None or row["status"] != "running" or row["lease_owner"] != worker_id
            or row["lease_expires_at"] is None or row["lease_expires_at"] <= timestamp
            or row["leader_epoch"] != claim["epoch"] or row["fence_token"] != claim["fence"]
            or lease["owner_id"] != worker_id or lease["epoch"] != claim["epoch"]
            or lease["lease_expires_at"] is None or lease["lease_expires_at"] <= timestamp):
            return None
        return row

    def wait_for_confirmation(self, worker_id, claim, continuation, kind="fake_approval", payload=None):
        from application.execution_continuation import ExecutionContinuation
        if not isinstance(continuation, ExecutionContinuation):
            raise TypeError("continuation_required")
        token = secrets.token_urlsafe(32)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._valid_claim(db, worker_id, claim)
            if row is None:
                db.rollback()
                return None
            revision = db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM execution_checkpoints WHERE run_id=?", (row["id"],)).fetchone()[0]
            checkpoint_id = uid()
            db.execute("INSERT INTO execution_checkpoints(id,run_id,continuation_json,revision,created_at) VALUES(?,?,?,?,?)",
                       (checkpoint_id, row["id"], continuation.to_json(), revision, now()))
            db.execute("INSERT INTO confirmations(id,task_id,run_id,checkpoint_id,checkpoint_revision,token_sha256,kind,payload_json,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (uid(), row["task_id"], row["id"], checkpoint_id, revision, hashlib.sha256(token.encode()).hexdigest(),
                        kind, json.dumps(payload or {}), "pending", (datetime.now(timezone.utc)+timedelta(hours=24)).isoformat(), now()))
            self._record_state(db, row, "waiting_confirmation")
            db.commit()
            return {"run_id": row["id"], "checkpoint_revision": revision, "token": token}

    def issue_resume_token(self, owner_id, run_id):
        token = secrets.token_urlsafe(32)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_run(db, owner_id, run_id)
            if row["current_run_id"] != run_id or row["status"] != "waiting_confirmation":
                raise ValueError("run_not_waiting")
            prior = db.execute("SELECT * FROM confirmations WHERE run_id=? AND kind<>'cancel' AND status='pending' ORDER BY created_at DESC LIMIT 1", (run_id,)).fetchone()
            if prior is None or prior["expires_at"] <= now():
                raise ValueError("confirmation_expired")
            db.execute("UPDATE confirmations SET status='superseded',rotated_at=? WHERE id=?", (now(), prior["id"]))
            db.execute("INSERT INTO confirmations(id,task_id,run_id,checkpoint_id,checkpoint_revision,token_sha256,kind,payload_json,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (uid(), row["task_id"], run_id, prior["checkpoint_id"], prior["checkpoint_revision"], hashlib.sha256(token.encode()).hexdigest(),
                        prior["kind"], prior["payload_json"], "pending", prior["expires_at"], now()))
            db.commit()
            return {"token": token, "run_id": run_id, "checkpoint_revision": prior["checkpoint_revision"],
                    "kind": prior["kind"], "payload": json.loads(prior["payload_json"]), "expires_at": prior["expires_at"]}

    def confirm(self, owner_id, run_id, token, checkpoint_revision):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_run(db, owner_id, run_id)
            if row["current_run_id"] != run_id or row["status"] != "waiting_confirmation":
                raise ValueError("run_not_waiting")
            latest = db.execute("SELECT * FROM execution_checkpoints WHERE run_id=? ORDER BY revision DESC LIMIT 1", (run_id,)).fetchone()
            confirmation = db.execute("SELECT * FROM confirmations WHERE run_id=? AND status='pending' AND kind<>'cancel' AND token_sha256=?", (run_id, digest)).fetchone()
            if (latest is None or confirmation is None or latest["revision"] != checkpoint_revision
                or confirmation["checkpoint_id"] != latest["id"] or confirmation["checkpoint_revision"] != checkpoint_revision
                or confirmation["expires_at"] <= now()):
                raise ValueError("invalid_confirmation_token")
            db.execute("UPDATE confirmations SET status='consumed',consumed_at=? WHERE id=?", (now(), confirmation["id"]))
            db.execute("UPDATE runs SET status='queued',queued_at=?,updated_at=?,revision=revision+1 WHERE id=?", (now(), now(), run_id))
            db.execute("UPDATE tasks SET status='queued',updated_at=?,revision=revision+1 WHERE id=?", (now(), row["task_id"]))
            self._run_event(db, run_id, "run_queued", "queued")
            self._event(db, row["conversation_id"], "run_queued", "run", run_id, {"run_id": run_id, "status": "queued", "resumed": True})
            db.commit()
            return {"id": run_id, "status": "queued"}

    def continuation(self, run_id):
        from application.execution_continuation import ExecutionContinuation
        with connect(self.path) as db:
            row = db.execute("SELECT continuation_json FROM execution_checkpoints WHERE run_id=? ORDER BY revision DESC LIMIT 1", (run_id,)).fetchone()
            return ExecutionContinuation.from_json(row["continuation_json"]) if row else None

    def publish(self, worker_id, claim, content: bytes, kind="fake_result", metadata=None, message=None):
        if not isinstance(content, bytes):
            raise TypeError("artifact_content_must_be_bytes")
        sha = hashlib.sha256(content).hexdigest()
        key = f"artifacts/{sha[:2]}/{sha}"
        stage = self.root / "staging" / (uid() + ".stage")
        final = self.root / key
        try:
            with stage.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if hashlib.sha256(stage.read_bytes()).hexdigest() != sha:
                raise OSError("staging_hash_mismatch")
            # The final Blob and its database reference share the same write lock
            # with startup reconciliation. A crash after rename may leave an orphan,
            # but a committed Artifact can never lose its Blob to reconciliation.
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._valid_claim(db, worker_id, claim)
                if row is None:
                    db.rollback()
                    return False
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage, final)
                # The rename is short, but fail closed if the lease expired while
                # the database lock was held.
                if self._valid_claim(db, worker_id, claim) is None:
                    db.rollback()
                    return False
                version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM artifacts WHERE task_id=? AND kind=?", (row["task_id"], kind)).fetchone()[0]
                artifact_id = uid()
                db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (artifact_id, row["conversation_id"], row["task_id"], row["id"], kind, version, "published", key, sha, json.dumps(metadata or {}, ensure_ascii=False), now(), len(content)))
                self._event(db, row["conversation_id"], "artifact_published", "artifact", artifact_id,
                            {"artifact_id": artifact_id, "run_id": row["id"], "kind": kind, "version": version})
                if message:
                    self._assistant_message(db, row["conversation_id"], message)
                self._record_state(db, row, "succeeded")
                db.commit()
                return True
        finally:
            stage.unlink(missing_ok=True)

    def publish_submission(self, worker_id, claim, producer, lease_seconds=30):
        """Commit knowledge application and terminal Run/Artifact in one SQLite transaction."""
        stage = self.root / "staging" / (uid() + ".stage")
        try:
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._valid_claim(db, worker_id, claim)
                if row is None:
                    db.rollback()
                    return False
                if not self._submission_is_current_db(db, claim):
                    self._assistant_message(db, row["conversation_id"], "主数据或分类结果已变化，请重新提取")
                    self._record_state(db, row, "failed", "log_knowledge_submission_stale")
                    db.commit()
                    return True
                db.execute("SAVEPOINT knowledge_submission")
                outcome = producer(db)
                status = outcome.get("submission_status")
                if status not in {"created", "pending_duplicate", "already_approved"}:
                    db.execute("ROLLBACK TO knowledge_submission")
                    db.execute("RELEASE knowledge_submission")
                    code = "log_knowledge_submission_stale" if status == "stale" else "log_knowledge_submission_error"
                    self._assistant_message(db, row["conversation_id"], "知识申请未提交，请检查结果后重试")
                    self._record_state(db, row, "failed", code)
                    db.commit()
                    return True
                db.execute("RELEASE knowledge_submission")
                content = json.dumps(outcome, ensure_ascii=False, sort_keys=True).encode("utf-8")
                sha = hashlib.sha256(content).hexdigest()
                with stage.open("wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                key = f"artifacts/{sha[:2]}/{sha}"
                final = self.root / key
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage, final)
                # The write lock prevented cancellation/takeover while the producer ran.
                deadline = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
                db.execute("UPDATE worker_leases SET lease_expires_at=? WHERE id='v2-primary'", (deadline,))
                db.execute("UPDATE runs SET lease_expires_at=? WHERE id=?", (deadline, claim["id"]))
                version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM artifacts WHERE task_id=? AND kind=?",
                                     (row["task_id"], "log_knowledge_submission")).fetchone()[0]
                artifact_id = uid()
                db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (artifact_id, row["conversation_id"], row["task_id"], row["id"], "log_knowledge_submission",
                            version, "published", key, sha,
                            json.dumps({"submission_status": status, "application_id": outcome.get("application_id")}), now(), len(content)))
                self._event(db, row["conversation_id"], "artifact_published", "artifact", artifact_id,
                            {"artifact_id": artifact_id, "run_id": row["id"], "kind": "log_knowledge_submission", "version": version})
                self._assistant_message(db, row["conversation_id"], "日志知识申请已处理")
                self._record_state(db, row, "succeeded")
                db.commit()
                return True
        finally:
            stage.unlink(missing_ok=True)

    def reconcile_blobs(self, retention_seconds=3600):
        cutoff = time.time() - retention_seconds
        for stage in (self.root / "staging").glob("*.stage"):
            try:
                if stage.stat().st_mtime <= cutoff:
                    stage.unlink(missing_ok=True)
            except FileNotFoundError:
                pass

        def identity(path):
            try:
                stat = path.stat()
                return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            except OSError:
                return None

        # Hashes and directory traversal are read-only and can be slow. Keep
        # them outside SQLite write transactions so a live Worker can renew.
        with connect(self.path) as db:
            published = db.execute("SELECT id,storage_key,sha256 FROM artifacts WHERE status='published'").fetchall()
        for row in published:
            path = self.root / row["storage_key"] if row["storage_key"] else None
            before = identity(path) if path else None
            try:
                valid = bool(path and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"])
            except OSError:
                valid = False
            if valid:
                continue
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT status,storage_key,sha256 FROM artifacts WHERE id=?", (row["id"],)).fetchone()
                if (current and current["status"] == "published"
                    and current["storage_key"] == row["storage_key"]
                    and current["sha256"] == row["sha256"]
                    and (identity(path) if path else None) == before):
                    db.execute("UPDATE artifacts SET status='corrupt' WHERE id=?", (row["id"],))
                db.commit()

        for path in (self.root / "artifacts").rglob("*"):
            try:
                if not path.is_file() or path.stat().st_mtime > cutoff:
                    continue
            except FileNotFoundError:
                continue
            key = path.relative_to(self.root).as_posix()
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                referenced = db.execute("SELECT 1 FROM artifacts WHERE storage_key=? LIMIT 1", (key,)).fetchone()
                try:
                    if not referenced and path.is_file() and path.stat().st_mtime <= cutoff:
                        path.unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
                db.commit()

    def enqueue_fake(self, owner_id, conversation_id, scenario="success", session_facts=None):
        if not self.settings.development:
            raise ValueError("fake_runs_disabled")
        if scenario not in ("success", "confirm", "fail"):
            raise ValueError("invalid_scenario")
        timestamp = now()
        task_id, run_id = uid(), uid()
        snapshot = {"scenario": scenario, "session_facts": session_facts or {}}
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.owns(db, conversation_id, owner_id)
            db.execute("INSERT INTO tasks(id,conversation_id,owner_id,type,status,current_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (task_id, conversation_id, owner_id, "fake_application", "queued", run_id, timestamp, timestamp))
            db.execute("INSERT INTO runs(id,task_id,attempt,status,input_snapshot_json,queued_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (run_id, task_id, 1, "queued", json.dumps(snapshot, sort_keys=True), timestamp, timestamp, timestamp))
            self._run_event(db, run_id, "run_queued", "queued")
            self._event(db, conversation_id, "run_queued", "run", run_id, {"run_id": run_id, "status": "queued"})
            db.commit()
        return {"task": {"id": task_id, "status": "queued"}, "run": {"id": run_id, "status": "queued"}}
