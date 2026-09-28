"""Transactional V2 storage, queue and file ingest operations."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os

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
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            for user_id, name, role in (("dev-user", "演示用户", "user"), ("dev-other", "开发者", "developer"), ("dev-admin", "管理员", "admin")):
                db.execute("INSERT OR IGNORE INTO users(id,display_name,role,is_active,created_at) VALUES(?,?,?,?,?)", (user_id, name, role, 1, now()))
            db.commit()

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
            runs = [self._run(r) for r in db.execute("SELECT r.*,t.conversation_id FROM runs r JOIN tasks t ON t.id=r.task_id WHERE t.conversation_id=? ORDER BY r.queued_at,r.id", (conversation_id,))]
            return {"id": row["id"], "title": row["title"], "created_at": row["created_at"], "updated_at": row["updated_at"], "messages": messages, "files": files, "runs": runs}

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

    def _file(self, row):
        return {"id": row["id"], "name": row["original_name"], "media_type": row["media_type"], "size": row["size"], "sha256": row["sha256"], "parse_status": row["parse_status"], "created_at": row["created_at"]}

    def _run(self, row):
        return {"id": row["id"], "task_id": row["task_id"], "status": row["status"], "attempt": row["attempt"], "queued_at": row["queued_at"], "started_at": row["started_at"], "finished_at": row["finished_at"], "error_code": row["error_code"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get_run(self, owner_id, run_id):
        with connect(self.path) as db:
            row = db.execute("SELECT r.*,t.conversation_id FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=? AND t.owner_id=?", (run_id, owner_id)).fetchone()
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
            epoch = lease["epoch"] + (1 if lease["owner_id"] != worker_id else 0)
            db.execute("UPDATE worker_leases SET owner_id=?,lease_expires_at=?,epoch=? WHERE id='v2-primary'", (worker_id, deadline, epoch))
            stale = db.execute("SELECT r.*,t.conversation_id FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.status='running' AND r.lease_expires_at<=?", (timestamp,)).fetchall()
            for abandoned in stale:
                db.execute("UPDATE runs SET status='failed',error_code='worker_lost',finished_at=?,updated_at=?,lease_owner=NULL,lease_expires_at=NULL,fence_token=NULL,revision=revision+1 WHERE id=? AND status='running'", (timestamp, timestamp, abandoned["id"]))
                db.execute("UPDATE tasks SET status='failed',updated_at=?,revision=revision+1 WHERE id=?", (timestamp, abandoned["task_id"]))
                snapshot = json.loads(abandoned["input_snapshot_json"])
                db.execute("UPDATE files SET parse_status='failed',updated_at=? WHERE id=?", (timestamp, snapshot["file_id"]))
                self._run_event(db, abandoned["id"], "run_failed", "failed")
                self._event(db, abandoned["conversation_id"], "run_failed", "run", abandoned["id"], {"run_id": abandoned["id"], "status": "failed", "error_code": "worker_lost"})
            row = db.execute("SELECT r.*,t.conversation_id FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.status='queued' ORDER BY r.queued_at,r.id LIMIT 1").fetchone()
            if row is None:
                db.commit()
                return None
            fence = uid()
            db.execute("UPDATE runs SET status='running',started_at=?,updated_at=?,lease_owner=?,lease_expires_at=?,leader_epoch=?,fence_token=?,revision=revision+1 WHERE id=?", (timestamp, timestamp, worker_id, deadline, epoch, fence, row["id"]))
            db.execute("UPDATE tasks SET status='running',updated_at=?,revision=revision+1 WHERE id=?", (timestamp, row["task_id"]))
            self._run_event(db, row["id"], "run_started", "running")
            self._event(db, row["conversation_id"], "run_started", "run", row["id"], {"run_id": row["id"], "status": "running"})
            db.commit()
            return {"id": row["id"], "task_id": row["task_id"], "conversation_id": row["conversation_id"], "input": json.loads(row["input_snapshot_json"]), "fence": fence, "epoch": epoch}

    def renew(self, worker_id, claim, lease_seconds=30):
        timestamp = now()
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT owner_id,epoch,lease_expires_at FROM worker_leases WHERE id='v2-primary'").fetchone()
            run = db.execute("SELECT status,lease_owner,fence_token FROM runs WHERE id=?", (claim["id"],)).fetchone()
            if (lease["owner_id"] != worker_id or lease["epoch"] != claim["epoch"] or lease["lease_expires_at"] <= timestamp or run is None or run["status"] != "running" or run["lease_owner"] != worker_id or run["fence_token"] != claim["fence"]):
                db.rollback()
                return False
            db.execute("UPDATE worker_leases SET lease_expires_at=? WHERE id='v2-primary'", (deadline,))
            db.execute("UPDATE runs SET lease_expires_at=? WHERE id=?", (deadline, claim["id"]))
            db.commit()
            return True

    def finish(self, worker_id, claim, error_code=None):
        status = "failed" if error_code else "succeeded"
        timestamp = now()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT owner_id,epoch,lease_expires_at FROM worker_leases WHERE id='v2-primary'").fetchone()
            run = db.execute("SELECT status,lease_owner,fence_token,leader_epoch FROM runs WHERE id=?", (claim["id"],)).fetchone()
            if (lease["owner_id"] != worker_id or lease["epoch"] != claim["epoch"] or lease["lease_expires_at"] <= timestamp or run["status"] != "running" or run["lease_owner"] != worker_id or run["fence_token"] != claim["fence"]):
                db.rollback()
                return False
            db.execute("UPDATE runs SET status=?,error_code=?,finished_at=?,updated_at=?,revision=revision+1 WHERE id=?", (status, error_code, timestamp, timestamp, claim["id"]))
            db.execute("UPDATE tasks SET status=?,updated_at=?,revision=revision+1 WHERE id=?", (status, timestamp, claim["task_id"]))
            db.execute("UPDATE files SET parse_status=?,updated_at=? WHERE id=?", (status, timestamp, claim["input"]["file_id"]))
            self._run_event(db, claim["id"], "run_" + status, status)
            self._event(db, claim["conversation_id"], "run_" + status, "run", claim["id"], {"run_id": claim["id"], "status": status, "error_code": error_code})
            db.commit()
            return True
