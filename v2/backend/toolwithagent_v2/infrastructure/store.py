"""Transactional V2 storage, queue and file ingest operations."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os
import re
import secrets
import time

from .db import connect, migrate
from contracts.model_call_diagnostics import redact_text
from toolwithagent_v2.runtime.progress import PROGRESS_FIELDS
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
        self._cached_master_key = None
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
            return [dict(r) for r in db.execute("""
                SELECT c.id,c.title,c.created_at,c.updated_at,
                  (SELECT r.status FROM tasks t JOIN runs r ON r.id=t.current_run_id
                   WHERE t.conversation_id=c.id AND t.owner_id=c.owner_id
                   ORDER BY r.created_at DESC,r.id DESC LIMIT 1) AS latest_run_status
                FROM conversations c WHERE c.owner_id=? AND c.archived_at IS NULL
                ORDER BY c.updated_at DESC,c.id DESC
            """, (owner_id,))]

    def create_conversation(self, owner_id, title):
        conversation_id, timestamp = uid(), now()
        title = (title or "新会话").strip()[:160] or "新会话"
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO conversations(id,owner_id,title,created_at,updated_at) VALUES(?,?,?,?,?)", (conversation_id, owner_id, title, timestamp, timestamp))
            self._event(db, conversation_id, "conversation_created", "conversation", conversation_id, {"title": title})
            db.commit()
        return {"id": conversation_id, "title": title, "created_at": timestamp, "updated_at": timestamp}

    def rename_conversation(self, owner_id, conversation_id, title):
        title = (title or "").strip()[:160]
        if not title:
            raise ValueError("invalid_conversation_title")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.owns(db, conversation_id, owner_id)
            timestamp = now()
            db.execute("UPDATE conversations SET title=?,updated_at=?,revision=revision+1 WHERE id=?", (title, timestamp, conversation_id))
            self._event(db, conversation_id, "conversation_renamed", "conversation", conversation_id, {"title": title})
            db.commit()
        return {"id": conversation_id, "title": title, "updated_at": timestamp}

    def get_conversation(self, owner_id, conversation_id):
        with connect(self.path) as db:
            row = self.owns(db, conversation_id, owner_id)
            messages = [dict(r) for r in db.execute("SELECT id,actor,kind,content_json,created_at FROM messages WHERE conversation_id=? ORDER BY created_at,id", (conversation_id,))]
            for m in messages:
                payload = json.loads(m.pop("content_json"))
                m["content"] = payload.get("text", "")
                m["payload"] = {key: value for key, value in payload.items() if key not in ("text", "run_id")}
                m["run_id"] = payload.get("run_id")
            files = [self._file(r) for r in db.execute("SELECT * FROM files WHERE conversation_id=? ORDER BY created_at,id", (conversation_id,))]
            current_file, _ = self._current_mapping_input(db, conversation_id)
            for file in files:
                file["mapping_eligible"] = bool(current_file and file["id"] == current_file["id"] and file["parse_status"] == "succeeded")
            runs = [self._run(r) for r in db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE t.conversation_id=? ORDER BY r.queued_at,r.id", (conversation_id,))]
            result = {"id": row["id"], "title": row["title"], "created_at": row["created_at"], "updated_at": row["updated_at"], "messages": messages, "files": files, "runs": runs, "artifacts": self._artifacts(db, conversation_id), "drafts": [self._draft_response(db,draft,summary=True) for draft in db.execute("SELECT * FROM drafts WHERE conversation_id=? AND owner_id=? AND status IN ('active','applying') ORDER BY created_at,id", (conversation_id,owner_id))]}
            result["field_changes"] = [dict(item) for item in db.execute("SELECT run_id,revision,status,apply_run_id,applied_artifact_id,undo_run_id,restored_artifact_id FROM field_change_previews WHERE conversation_id=? AND owner_id=? ORDER BY created_at,run_id", (conversation_id, owner_id))]
            result.update(self._conversation_facts(db, owner_id, conversation_id))
            return result

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
            from application.request_runtime import is_explicit_clear_command
            clear = is_explicit_clear_command(content)
            if clear:
                # 冻结清空范围，之后上传的新输入不属于本次用户命令。
                clear_boundary = {"file_ids": [row["id"] for row in db.execute("SELECT id FROM files WHERE conversation_id=?", (conversation_id,))],
                    "artifact_ids": [row["id"] for row in db.execute("SELECT id FROM artifacts WHERE conversation_id=?", (conversation_id,))],
                    "run_ids": [row["id"] for row in db.execute("SELECT r.id FROM runs r JOIN tasks t ON t.id=r.task_id WHERE t.conversation_id=?", (conversation_id,))]}
                # 入队即取消旧活动运行，释放同会话串行队列并关闭旧 Worker 的发布资格。
                self._cancel_business_runs(db, conversation_id)
                db.execute("UPDATE drafts SET status='discarded',updated_at=?,revision=revision+1 WHERE conversation_id=? AND status IN ('active','applying')", (timestamp, conversation_id))
            else:
                if db.execute("SELECT 1 FROM drafts WHERE conversation_id=? AND owner_id=? AND status IN ('active','applying') AND changed_count>0 LIMIT 1", (conversation_id,owner_id)).fetchone():
                    raise ValueError("draft_resolution_required")
                self._business_command_guard(db, owner_id, conversation_id)
            db.execute("INSERT INTO messages(id,conversation_id,actor,kind,content_json,created_at) VALUES(?,?,?,?,?,?)", (message_id, conversation_id, "user", "text", json.dumps({"text": content}, ensure_ascii=False), timestamp))
            db.execute("UPDATE conversations SET updated_at=?,revision=revision+1 WHERE id=?", (timestamp, conversation_id))
            self._event(db, conversation_id, "message_created", "message", message_id, {"actor": "user"})
            snapshot = {"clear_boundary": clear_boundary} if clear else self._freeze_business(db, conversation_id)
            snapshot.update({"message_id": message_id, "user_text": content})
            queued = self._enqueue_task(db, owner_id, conversation_id, "business_clear" if clear else "user_request", snapshot)
            result = {"id": message_id, "actor": "user", "kind": "text", "content": content, "created_at": timestamp, **queued}
            if idempotency_key:
                db.execute("INSERT INTO idempotency_receipts(id,principal_id,operation_scope,key,request_sha256,status,result_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid(), owner_id, "message:" + conversation_id, idempotency_key, request_hash, "completed", json.dumps(result, ensure_ascii=False), timestamp))
            db.commit()
        return result

    def upload(self, owner_id, conversation_id, upload, idempotency_key=None, role="primary"):
        if role not in {"primary", "enum_mapping"}:
            raise ValueError("invalid_upload_role")
        with connect(self.path) as db:
            self.owns(db, conversation_id, owner_id)
        original = Path(upload.filename or "upload").name[:255]
        suffix = Path(original).suffix.lower()
        media = {".csv":"text/csv", ".txt":"text/plain", ".log":"text/plain", ".json":"application/json", ".jsonl":"application/x-ndjson", ".xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".b64":"text/plain"}.get(suffix)
        if media is None:
            raise ValueError("unsupported_file_type")
        if role == "enum_mapping" and suffix != ".xlsx":
            raise ValueError("enum_attachment_requires_xlsx")
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
            request_hash = hashlib.sha256(json.dumps([conversation_id, original, media, sha, role], separators=(",", ":")).encode()).hexdigest()
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
                usage = "枚举映射附件" if role == "enum_mapping" else "主数据"
                message_id = self._input_record_message(db, conversation_id, "file",
                    {"text": f"上传了{usage}「{original}」", "action": "file_upload", "file_id": file_id,
                     "name": original, "media_type": media, "size": size, "role": role})
                db.execute("INSERT INTO files(id,owner_id,conversation_id,original_name,media_type,size,sha256,storage_key,parse_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (file_id, owner_id, conversation_id, original, media, size, sha, key, "queued", timestamp, timestamp))
                db.execute("UPDATE files SET role=? WHERE id=?", (role, file_id))
                db.execute("INSERT INTO tasks(id,conversation_id,owner_id,type,status,current_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (task_id, conversation_id, owner_id, "file_ingest", "queued", run_id, timestamp, timestamp))
                db.execute("INSERT INTO runs(id,task_id,attempt,status,input_snapshot_json,queued_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (run_id, task_id, 1, "queued", json.dumps({"file_id": file_id, "sha256": sha, "storage_key": key, "media_type": media, "role": role, "original_name": original, "message_id": message_id}, separators=(",", ":")), timestamp, timestamp, timestamp))
                db.execute("UPDATE conversations SET updated_at=?,revision=revision+1 WHERE id=?", (timestamp, conversation_id))
                self._run_event(db, run_id, "run_queued", "queued")
                self._event(db, conversation_id, "file_uploaded", "file", file_id, {"file_id": file_id, "name": original})
                self._event(db, conversation_id, "run_queued", "run", run_id, {"run_id": run_id, "status": "queued"})
                result = {"file": {"id": file_id, "name": original, "media_type": media, "size": size, "sha256": sha, "parse_status": "queued", "role": role, "created_at": timestamp}, "task": {"id": task_id, "status": "queued"}, "run": {"id": run_id, "status": "queued"}, "message": {"id": message_id, "kind": "file"}}
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
            file = db.execute("SELECT * FROM files WHERE id=? AND conversation_id=? AND owner_id=? AND is_active=1", (file_id, conversation_id, owner_id)).fetchone()
            if file is None:
                raise LookupError("file_not_found")
            if file["parse_status"] != "succeeded":
                raise ValueError("file_not_validated")
            if file["media_type"] not in {"text/plain", "application/json", "application/x-ndjson", "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
                raise ValueError("unsupported_log_type")
            message_id = self._input_record_message(db, conversation_id, "operation",
                {"text": "提交日志类型提取", "action": "log_parse", "file_id": file_id,
                 "name": file["original_name"], "feature_field": feature_field})
            snapshot = {key: file[key] for key in ("sha256", "storage_key", "media_type")}
            snapshot.update({"file_id": file_id, "feature_field": feature_field, "message_id": message_id})
            result = self._enqueue_task(db, owner_id, conversation_id, "log_parse", snapshot)
            result["message"] = {"id": message_id, "kind": "operation"}
            db.commit()
            return result

    def _current_mapping_input(self, db, conversation_id):
        file = db.execute("SELECT * FROM files WHERE conversation_id=? AND role='primary' AND is_active=1 AND parse_status='succeeded' ORDER BY created_at DESC,id DESC LIMIT 1", (conversation_id,)).fetchone()
        classification = db.execute("SELECT a.*,r.input_snapshot_json FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.conversation_id=? AND a.kind='log_classification' AND a.status='published' AND json_extract(r.input_snapshot_json,'$.file_id')=? ORDER BY a.created_at DESC,a.id DESC LIMIT 1", (conversation_id, file['id'] if file else None)).fetchone()
        return file, classification

    def enqueue_field_mapping(self, owner_id, conversation_id, *, file_id=None, classification_artifact_id=None,
                              product, log_vendor, data_source="", idempotency_key=None):
        from contracts.rule_source import RuleSourceFields
        if bool(file_id) == bool(classification_artifact_id):
            raise ValueError("mapping_input_required")
        if any(len(str(value)) > 160 for value in (product, log_vendor, data_source)):
            raise ValueError("invalid_source_fields")
        try:
            fields = RuleSourceFields.create(product=product, log_vendor=log_vendor, data_source=data_source)
        except ValueError:
            raise ValueError("data_source_fields_required") from None
        source_fields = {"product": fields.product, "log_vendor": fields.log_vendor, "data_source": fields.data_source}
        request_hash = hashlib.sha256(json.dumps([file_id, classification_artifact_id, source_fields], sort_keys=True).encode()).hexdigest()
        scope = "field-mapping:" + conversation_id
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.owns(db, conversation_id, owner_id)
            if idempotency_key:
                receipt = db.execute("SELECT request_sha256,result_json FROM idempotency_receipts WHERE principal_id=? AND operation_scope=? AND key=?", (owner_id, scope, idempotency_key)).fetchone()
                if receipt:
                    if receipt["request_sha256"] != request_hash:
                        raise ValueError("idempotency_key_reused")
                    return json.loads(receipt["result_json"])
            current, classification = self._current_mapping_input(db, conversation_id)
            if classification_artifact_id:
                source = db.execute("SELECT a.*,r.input_snapshot_json FROM artifacts a JOIN tasks t ON t.id=a.task_id JOIN runs r ON r.id=a.run_id WHERE a.id=? AND a.conversation_id=? AND t.owner_id=? AND a.kind='log_classification' AND a.status='published'", (classification_artifact_id, conversation_id, owner_id)).fetchone()
                if source is None:
                    raise LookupError("artifact_not_found")
                snapshot = json.loads(source["input_snapshot_json"])
                file_id = snapshot["file_id"]
                if classification is None or classification["id"] != classification_artifact_id:
                    raise ValueError("mapping_input_stale")
            else:
                # 文件入口与显式分类入口同源：锚定当前分类产物，映射执行期不再隐式重复解析（#432）。
                source = classification
            file = db.execute("SELECT * FROM files WHERE id=? AND conversation_id=? AND owner_id=? AND is_active=1", (file_id, conversation_id, owner_id)).fetchone()
            if file is None:
                raise LookupError("file_not_found")
            if file["parse_status"] != "succeeded":
                raise ValueError("file_not_validated")
            if current is None or current["id"] != file_id:
                raise ValueError("mapping_input_stale")
            snapshot = {key: file[key] for key in ("sha256", "storage_key", "media_type")}
            snapshot.update({"file_id": file_id, "source_fields": source_fields,
                             "classification_anchor": classification["id"] if classification else None,
                             "mapping_edit_anchor": self._mapping_edit_anchor(db,conversation_id)})
            if source is not None:
                snapshot.update({"source_artifact_id":source["id"], "source_sha256":source["sha256"], "source_storage_key":source["storage_key"],
                                 "feature_field":json.loads(source["input_snapshot_json"]).get("feature_field")})
            snapshot["business_inputs"] = self._freeze_business(db, conversation_id)["business_inputs"]
            message_id = self._input_record_message(db, conversation_id, "operation",
                {"text": f"提交标准字段映射：产品 {source_fields['product']} · 厂商 {source_fields['log_vendor']}",
                 "action": "field_mapping", "file_id": file_id,
                 "classification_artifact_id": classification_artifact_id, **source_fields})
            snapshot["message_id"] = message_id
            result = self._enqueue_task(db, owner_id, conversation_id, "field_mapping", snapshot)
            result["message"] = {"id": message_id, "kind": "operation"}
            if idempotency_key:
                db.execute("INSERT INTO idempotency_receipts(id,principal_id,operation_scope,key,request_sha256,status,result_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid(), owner_id, scope, idempotency_key, request_hash, "completed", json.dumps(result), now()))
            db.commit()
            return result

    def _mapping_is_current_db(self, db, claim):
        file, classification = self._current_mapping_input(db, claim["conversation_id"])
        snapshot = claim["input"]
        return bool(file and file["id"] == snapshot["file_id"] and
                    (classification["id"] if classification else None) == snapshot.get("classification_anchor"))

    def mapping_is_current(self, claim):
        with connect(self.path) as db:
            return self._mapping_is_current_db(db, claim)

    def _owned_mapping(self, owner_id, artifact_id):
        with connect(self.path) as db:
            row = db.execute("SELECT a.* FROM artifacts a JOIN tasks t ON t.id=a.task_id WHERE a.id=? AND a.kind='field_mapping' AND a.status IN ('published','stale') AND t.owner_id=?", (artifact_id,owner_id)).fetchone()
            if row is None:
                raise LookupError("artifact_not_found")
        key = row["storage_key"]
        if not key.startswith("artifacts/") or ".." in key.split("/"):
            raise ValueError("artifact_corrupt")
        path = (self.root / key).resolve()
        if not path.is_relative_to((self.root / "artifacts").resolve()):
            raise ValueError("artifact_corrupt")
        try:
            content = path.read_bytes()
        except OSError:
            raise ValueError("artifact_corrupt") from None
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("artifact_corrupt")
        return dict(row), json.loads(content)

    def mapping_view(self, owner_id, artifact_id, sub_rule=None, page=1, q="", status=None, draft_id=None):
        from toolwithagent_v2.runtime.mapping_projection import mapping_view
        _row, payload = self._owned_mapping(owner_id, artifact_id)
        draft = None
        if draft_id:
            from toolwithagent_v2.runtime.mapping_drafts import project_payload
            with connect(self.path) as db:
                row = self._owned_draft(db,owner_id,draft_id)
                if row["base_artifact_id"] != artifact_id:
                    raise LookupError("mapping_draft_not_found")
                payload = project_payload(payload,self._draft_operations(db,draft_id),editing=True)
                draft = self._draft_response(db,row)
        return {"artifact_id": artifact_id, "draft": draft, **mapping_view(payload, sub_rule, page, q, status)}

    def _mapping_base_current_db(self, db, artifact_id, conversation_id):
        row = db.execute("SELECT a.*,r.input_snapshot_json FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.id=? AND a.conversation_id=? AND a.kind='field_mapping' AND a.status='published'", (artifact_id, conversation_id)).fetchone()
        latest = db.execute("SELECT id FROM artifacts WHERE conversation_id=? AND kind='field_mapping' AND status='published' ORDER BY created_at DESC,id DESC LIMIT 1", (conversation_id,)).fetchone()
        return bool(row and latest and latest["id"] == artifact_id and self._mapping_is_current_db(db, {"conversation_id": conversation_id, "input": json.loads(row["input_snapshot_json"])}))

    def _mapping_edit_anchor(self, db, conversation_id):
        row = db.execute("SELECT a.id FROM artifacts a JOIN tasks t ON t.id=a.task_id WHERE a.conversation_id=? AND a.kind='field_mapping' AND a.status IN ('published','stale') AND t.type='mapping_draft_apply' ORDER BY a.created_at DESC,a.id DESC LIMIT 1", (conversation_id,)).fetchone()
        return row["id"] if row else None

    def _owned_draft(self, db, owner_id, draft_id):
        row = db.execute("SELECT * FROM drafts WHERE id=? AND owner_id=? AND kind='field_mapping'", (draft_id, owner_id)).fetchone()
        if row is None:
            raise LookupError("mapping_draft_not_found")
        self.owns(db, row["conversation_id"], owner_id)
        return row

    def _draft_operations(self, db, draft_id):
        return [json.loads(row["after_json"]) for row in db.execute("SELECT after_json FROM draft_operations WHERE draft_id=? ORDER BY created_at,id", (draft_id,))]

    def _draft_response(self, db, row, *, summary=False):
        artifact = db.execute("SELECT id FROM artifacts WHERE run_id=? AND kind='field_mapping' AND status IN ('published','stale')", (row["apply_run_id"],)).fetchone()
        result = {"id": row["id"], "conversation_id": row["conversation_id"], "base_artifact_id": row["base_artifact_id"],
                  "revision": row["revision"], "status": row["status"], "changed_count": row["changed_count"],
                  "apply_run_id": row["apply_run_id"], "applied_artifact_id": artifact["id"] if artifact else None,
                  "base_current": self._mapping_base_current_db(db, row["base_artifact_id"], row["conversation_id"])}
        if not summary:
            result["operations"] = self._draft_operations(db, row["id"])
            result["operation_count"] = len(result["operations"])
        return result

    def _draft_revision(self, row, revision, *, writable=True):
        from toolwithagent_v2.runtime.mapping_drafts import DraftError
        if row["revision"] != revision:
            raise DraftError("draft_revision_conflict", {"revision": row["revision"]})
        if writable and row["status"] != "active":
            raise DraftError("draft_apply_in_progress" if row["status"] == "applying" else "draft_not_editable")

    def create_mapping_draft(self, owner_id, artifact_id):
        self._owned_mapping(owner_id, artifact_id)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            artifact = db.execute("SELECT conversation_id FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
            self.owns(db, artifact["conversation_id"], owner_id)
            if not self._mapping_base_current_db(db, artifact_id, artifact["conversation_id"]):
                raise ValueError("mapping_base_stale")
            row = db.execute("SELECT * FROM drafts WHERE owner_id=? AND base_artifact_id=? AND status IN ('active','applying')", (owner_id, artifact_id)).fetchone()
            if row is None:
                draft_id, timestamp = uid(), now()
                db.execute("INSERT INTO drafts(id,owner_id,conversation_id,kind,status,revision,created_at,updated_at,base_artifact_id) VALUES(?,?,?,'field_mapping','active',1,?,?,?)", (draft_id,owner_id,artifact["conversation_id"],timestamp,timestamp,artifact_id))
                row = self._owned_draft(db, owner_id, draft_id)
            result = self._draft_response(db, row)
            db.commit()
            return result

    def get_mapping_draft(self, owner_id, draft_id):
        with connect(self.path) as db:
            return self._draft_response(db, self._owned_draft(db, owner_id, draft_id))

    def standard_fields(self, owner_id, draft_id=None, sub_rule=None, q=""):
        from agent.core.standard_field_catalog import get_standard_field_catalog
        from agent.tools.rule_generator.field_mapping import MAPPING_EXCLUDED_STANDARD_FIELDS
        from toolwithagent_v2.runtime.mapping_drafts import project_payload
        if len(q) > 200:
            raise ValueError("invalid_mapping_query")
        occupied = {}
        if draft_id:
            with connect(self.path) as db:
                draft = self._owned_draft(db, owner_id, draft_id)
                _artifact, base = self._owned_mapping(owner_id, draft["base_artifact_id"])
                payload = project_payload(base, self._draft_operations(db, draft_id))
            rules = payload["config"]
            selected = str(sub_rule) if sub_rule is not None else "0"
            if not selected.isdecimal() or str(int(selected)) != selected or int(selected) >= len(rules):
                raise ValueError("mapping_sub_rule_not_found")
            occupied = {str(entry["field"]): entry["index"] for entry in rules[int(selected)].get("normalize", []) if entry.get("field")}
        query = q.strip().casefold()
        return {"items": [{"name": field.system_property_name, "category": field.category,
                           "occupied_by": occupied.get(field.system_property_name), "disabled_reason": None}
                          for field in get_standard_field_catalog().fields
                          if field.system_property_name not in MAPPING_EXCLUDED_STANDARD_FIELDS
                          and (not query or query in field.system_property_name.casefold())]}

    def save_mapping_operation(self, owner_id, draft_id, key, proposal, revision, *, replace=False):
        from toolwithagent_v2.runtime.mapping_drafts import effective_changes, prepare_operation
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_draft(db, owner_id, draft_id)
            self._draft_revision(row, revision)
            if not self._mapping_base_current_db(db, row["base_artifact_id"], row["conversation_id"]):
                raise ValueError("mapping_base_stale")
            _artifact, base = self._owned_mapping(owner_id, row["base_artifact_id"])
            operations = self._draft_operations(db, draft_id)
            operation, choices, modified = prepare_operation(base, operations, key, proposal, replace=replace)
            previous = next((item for item in operations if item["operation_key"] == key), None)
            if modified and (previous is not None or operation["changes"]):
                db.execute("DELETE FROM draft_operations WHERE draft_id=? AND operation_key=?", (draft_id,key))
                if operation["changes"]:
                    db.execute("INSERT INTO draft_operations(id,draft_id,operation_key,scope_json,before_json,after_json,validation_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid(),draft_id,key,json.dumps(proposal,ensure_ascii=False),"{}",json.dumps(operation,ensure_ascii=False),"{}",now()))
                operations = self._draft_operations(db, draft_id)
                count = len(effective_changes(base, operations))
                db.execute("UPDATE drafts SET revision=revision+1,changed_count=?,updated_at=? WHERE id=?", (count,now(),draft_id))
            row = self._owned_draft(db, owner_id, draft_id)
            result = {"draft": self._draft_response(db,row), "candidates": choices}
            db.commit()
            return result

    def mapping_candidates(self, owner_id, draft_id, key):
        from toolwithagent_v2.runtime.mapping_drafts import candidates, project_payload
        with connect(self.path) as db:
            row = self._owned_draft(db, owner_id, draft_id)
            operations = self._draft_operations(db, draft_id)
            operation = next((item for item in operations if item["operation_key"] == key), None)
            if operation is None:
                raise LookupError("mapping_operation_not_found")
            _artifact, base = self._owned_mapping(owner_id, row["base_artifact_id"])
            return candidates(project_payload(base, operations), operation["proposal"])

    def _draft_receipt(self, db, owner_id, scope, key, request):
        if not key or len(key) > 200:
            raise ValueError("idempotency_key_required")
        digest = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        receipt = db.execute("SELECT * FROM idempotency_receipts WHERE principal_id=? AND operation_scope=? AND key=?", (owner_id,scope,key)).fetchone()
        if receipt and receipt["request_sha256"] != digest:
            raise ValueError("idempotency_key_reused")
        return digest, json.loads(receipt["result_json"]) if receipt else None

    def _save_draft_receipt(self, db, owner_id, scope, key, digest, result):
        db.execute("INSERT INTO idempotency_receipts(id,principal_id,operation_scope,key,request_sha256,status,result_json,created_at) VALUES(?,?,?,?,?,'completed',?,?)", (uid(),owner_id,scope,key,digest,json.dumps(result,ensure_ascii=False),now()))

    def confirm_mapping_replacement(self, owner_id, draft_id, key, proposal, confirm, revision, idempotency_key):
        # Confirm and its receipt share the save transaction via the same connection.
        from toolwithagent_v2.runtime.mapping_drafts import effective_changes, prepare_operation
        scope = "mapping-replacement:" + draft_id
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_draft(db, owner_id, draft_id)
            digest, existing = self._draft_receipt(db,owner_id,scope,idempotency_key,[key,proposal,confirm,revision])
            if existing is not None:
                return existing
            self._draft_revision(row,revision)
            if not self._mapping_base_current_db(db,row["base_artifact_id"],row["conversation_id"]):
                raise ValueError("mapping_base_stale")
            if confirm:
                _artifact,base = self._owned_mapping(owner_id,row["base_artifact_id"])
                operations = self._draft_operations(db,draft_id)
                operation, choices, modified = prepare_operation(base,operations,key,proposal,replace=True)
                previous = next((item for item in operations if item["operation_key"] == key), None)
                if modified and (previous is not None or operation["changes"]):
                    db.execute("DELETE FROM draft_operations WHERE draft_id=? AND operation_key=?", (draft_id,key))
                    if operation["changes"]:
                        db.execute("INSERT INTO draft_operations(id,draft_id,operation_key,scope_json,before_json,after_json,validation_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (uid(),draft_id,key,json.dumps(proposal,ensure_ascii=False),"{}",json.dumps(operation,ensure_ascii=False),"{}",now()))
                    db.execute("UPDATE drafts SET revision=revision+1,changed_count=?,updated_at=? WHERE id=?", (len(effective_changes(base,self._draft_operations(db,draft_id))),now(),draft_id))
                result = {"draft":self._draft_response(db,self._owned_draft(db,owner_id,draft_id)),"candidates":choices}
            else:
                result = {"draft":self._draft_response(db,row),"candidates":None}
            self._save_draft_receipt(db,owner_id,scope,idempotency_key,digest,result)
            db.commit()
            return result

    def discard_mapping_draft(self, owner_id, draft_id, revision):
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_draft(db,owner_id,draft_id)
            self._draft_revision(row,revision)
            db.execute("UPDATE drafts SET status='discarded',revision=revision+1,updated_at=? WHERE id=?", (now(),draft_id))
            result = self._draft_response(db,self._owned_draft(db,owner_id,draft_id))
            db.commit()
            return result

    def apply_mapping_draft(self, owner_id, draft_id, revision, idempotency_key):
        from toolwithagent_v2.runtime.mapping_drafts import catalog_version, project_payload
        scope = "mapping-apply:" + draft_id
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_draft(db,owner_id,draft_id)
            digest,existing = self._draft_receipt(db,owner_id,scope,idempotency_key,[row["base_artifact_id"],revision])
            if existing is not None:
                return existing
            self._draft_revision(row,revision)
            if not row["changed_count"]:
                raise ValueError("mapping_draft_empty")
            if not self._mapping_base_current_db(db,row["base_artifact_id"],row["conversation_id"]):
                raise ValueError("mapping_base_stale")
            artifact,base = self._owned_mapping(owner_id,row["base_artifact_id"])
            operations = self._draft_operations(db,draft_id)
            project_payload(base,operations)  # Fail before creating a Task for invalid configuration.
            original = db.execute("SELECT * FROM runs WHERE id=?", (artifact["run_id"],)).fetchone()
            snapshot = json.loads(original["input_snapshot_json"])
            snapshot.update({"base_artifact_id":artifact["id"], "base_sha256":artifact["sha256"], "base_storage_key":artifact["storage_key"],
                             "draft_id":draft_id,"draft_revision":revision,"draft_operations":operations,"catalog_version":catalog_version()})
            result = self._enqueue_task(db,owner_id,row["conversation_id"],"mapping_draft_apply",snapshot)
            db.execute("UPDATE runs SET provider_config_revision=?,prompt_version=?,standard_field_version=? WHERE id=?", (original["provider_config_revision"],original["prompt_version"],original["standard_field_version"],result["run"]["id"]))
            db.execute("UPDATE drafts SET status='applying',apply_run_id=?,updated_at=? WHERE id=?", (result["run"]["id"],now(),draft_id))
            result["draft"] = self._draft_response(db,self._owned_draft(db,owner_id,draft_id))
            self._save_draft_receipt(db,owner_id,scope,idempotency_key,digest,result)
            db.commit()
            return result

    def _draft_apply_current_db(self, db, claim):
        from toolwithagent_v2.runtime.mapping_drafts import catalog_version
        snapshot = claim["input"]
        row = db.execute("SELECT * FROM drafts WHERE id=? AND owner_id=?", (snapshot["draft_id"],claim["owner_id"])).fetchone()
        artifact = db.execute("SELECT sha256,storage_key FROM artifacts WHERE id=?", (snapshot["base_artifact_id"],)).fetchone()
        return bool(row and row["status"] == "applying" and row["apply_run_id"] == claim["id"]
                    and row["revision"] == snapshot["draft_revision"] and row["base_artifact_id"] == snapshot["base_artifact_id"]
                    and artifact and artifact["sha256"] == snapshot["base_sha256"] and artifact["storage_key"] == snapshot["base_storage_key"]
                    and snapshot["catalog_version"] == catalog_version()
                    and self._mapping_base_current_db(db,row["base_artifact_id"],row["conversation_id"]))

    def read_mapping_draft_apply(self, claim):
        with connect(self.path) as db:
            if not self._draft_apply_current_db(db,claim):
                raise ValueError("mapping_draft_apply_stale")
        _artifact,base = self._owned_mapping(claim["owner_id"],claim["input"]["base_artifact_id"])
        return base

    def _release_mapping_draft(self, db, run_id):
        db.execute("UPDATE drafts SET status='active',updated_at=? WHERE status='applying' AND apply_run_id=?", (now(),run_id))

    def mapping_download(self, owner_id, artifact_id):
        from application.download_names import download_filename
        row, payload = self._owned_mapping(owner_id, artifact_id)
        timestamp = datetime.fromisoformat(row["created_at"]).astimezone().strftime("%Y%m%d_%H%M")
        name = download_filename(payload["download_kind"], timestamp)
        return name, payload["download_content"].encode("utf-8")

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
            latest_file = db.execute("SELECT id FROM files WHERE conversation_id=? AND role='primary' AND is_active=1 AND parse_status='succeeded' ORDER BY created_at DESC,id DESC LIMIT 1", (artifact["conversation_id"],)).fetchone()
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
            message_id = self._input_record_message(db, artifact["conversation_id"], "operation",
                {"text": "提交日志知识申请", "action": "log_knowledge_submit", "source_artifact_id": artifact_id})
            result = self._enqueue_task(db, owner_id, artifact["conversation_id"], "log_knowledge_submit",
                {**source, "source_artifact_id": artifact_id, "source_sha256": artifact["sha256"],
                 "source_storage_key": artifact["storage_key"], "message_id": message_id})
            result["message"] = {"id": message_id, "kind": "operation"}
            db.commit()
            return result

    def _submission_is_current_db(self, db, claim):
        snapshot = claim["input"]
        file = db.execute("SELECT id FROM files WHERE conversation_id=? AND role='primary' AND is_active=1 AND parse_status='succeeded' ORDER BY created_at DESC,id DESC LIMIT 1",
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
            AND a.kind='log_classification' AND a.status IN ('published','stale') ORDER BY a.created_at,a.id""",
            (conversation_id,)).fetchall()
        result = []
        latest_file = db.execute("SELECT id FROM files WHERE conversation_id=? AND role='primary' AND is_active=1 AND parse_status='succeeded' ORDER BY created_at DESC,id DESC LIMIT 1", (conversation_id,)).fetchone()
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
                "submission_eligible": row["status"] == "published" and bool(metadata.get("submission_eligible")) and bool(latest_file) and latest_file["id"] == json.loads(row["input_snapshot_json"])["file_id"] and row["id"] == latest_artifact_id,
                "current": row["status"] == "published" and bool(latest_file) and latest_file["id"] == json.loads(row["input_snapshot_json"])["file_id"] and row["id"] == latest_artifact_id,
                "mapping_eligible": row["status"] == "published" and bool(latest_file) and latest_file["id"] == json.loads(row["input_snapshot_json"])["file_id"] and row["id"] == latest_artifact_id,
                "submission_status": status, "application_id": application_id,
                "created_at": row["created_at"]})
        mapping_rows = db.execute("SELECT a.*,r.input_snapshot_json FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.conversation_id=? AND a.kind='field_mapping' AND a.status IN ('published','stale') ORDER BY a.created_at,a.id", (conversation_id,)).fetchall()
        published_mappings = [row for row in mapping_rows if row["status"] == "published"]
        latest_mapping_id = published_mappings[-1]["id"] if published_mappings else None
        for row in mapping_rows:
            snapshot = json.loads(row["input_snapshot_json"])
            current = row["id"] == latest_mapping_id and self._mapping_is_current_db(db, {"conversation_id":conversation_id, "input":snapshot})
            result.append({"id":row["id"], "run_id":row["run_id"], "file_id":snapshot["file_id"],
                "kind":row["kind"], "status":"published" if current else "stale", "current":current,
                "source_artifact_id":snapshot.get("source_artifact_id"), "message_id": snapshot.get("message_id"), "result_message_id": json.loads(row["metadata_json"]).get("result_message_id"), "config_ref": json.loads(row["metadata_json"]).get("config_ref", "session.mapped_sub_rules"), "summary":json.loads(row["metadata_json"]).get("summary",{}),
                "created_at":row["created_at"]})
        for row in db.execute("SELECT a.*,r.input_snapshot_json FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.conversation_id=? AND a.kind IN ('enum_values','threat_mapping','config_export') AND a.status IN ('published','stale') ORDER BY a.created_at,a.id", (conversation_id,)):
            metadata = json.loads(row["metadata_json"])
            snapshot = json.loads(row["input_snapshot_json"])
            current = row["status"] == "published" and bool(latest_file) and latest_file["id"] == snapshot.get("file_id")
            if row["kind"] == "config_export":
                sources = db.execute("SELECT a.status,r.input_snapshot_json FROM artifact_edges e JOIN artifacts a ON a.id=e.source_artifact_id JOIN runs r ON r.id=a.run_id WHERE e.derived_artifact_id=? AND a.kind='field_mapping'", (row["id"],)).fetchall()
                current = current and all(source["status"] == "published" and self._mapping_is_current_db(db, {"conversation_id": conversation_id, "input": json.loads(source["input_snapshot_json"])}) for source in sources)
            result.append({"id": row["id"], "run_id": row["run_id"], "file_id": snapshot.get("file_id"), "kind": row["kind"], "status": "published" if current else "stale", "current": current, "summary": metadata.get("summary", {}), "source_field": metadata.get("source_field"), "message_id": metadata.get("message_id"), "result_message_id": metadata.get("result_message_id"), "created_at": row["created_at"]})
        versions = {row["id"]: row["version"] for row in db.execute(
            "SELECT id,version FROM artifacts WHERE conversation_id=?", (conversation_id,))}
        sources = {}
        for edge in db.execute(
            "SELECT e.source_artifact_id,e.derived_artifact_id FROM artifact_edges e"
            " JOIN artifacts a ON a.id=e.derived_artifact_id WHERE a.conversation_id=?"
            " ORDER BY e.derived_artifact_id,e.source_artifact_id", (conversation_id,)):
            sources.setdefault(edge["derived_artifact_id"], []).append(edge["source_artifact_id"])
        for item in result:
            item["version"] = versions[item["id"]]
            item["source_artifact_ids"] = sources.get(item["id"], [])
        return result

    def _file(self, row):
        return {"id": row["id"], "name": row["original_name"], "media_type": row["media_type"], "size": row["size"], "sha256": row["sha256"], "parse_status": row["parse_status"], "role": row["role"], "active": bool(row["is_active"]), "created_at": row["created_at"]}

    def _run(self, row):
        return {"id": row["id"], "task_id": row["task_id"], "kind": row["task_type"], "message_id": json.loads(row["input_snapshot_json"]).get("message_id"), "file_id": json.loads(row["input_snapshot_json"]).get("file_id"), "status": row["status"], "attempt": row["attempt"], "queued_at": row["queued_at"], "started_at": row["started_at"], "finished_at": row["finished_at"], "error_code": row["error_code"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get_run(self, owner_id, run_id):
        with connect(self.path) as db:
            row = db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=? AND t.owner_id=?", (run_id, owner_id)).fetchone()
            if row is None:
                raise LookupError("run_not_found")
            result = self._run(row)
            result["events"] = [{**dict(event), "summary": json.loads(event["summary_json"])} for event in db.execute("SELECT sequence,scope_type,scope_id,event_type,status,summary_json,created_at FROM run_events WHERE run_id=? ORDER BY sequence", (run_id,))]
            for event in result["events"]:
                event.pop("summary_json")
            return result

    def diagnostic_run(self, run_id, include_content=False):
        """Project one Run's linked evidence without reading unrelated conversations."""
        with connect(self.path) as db:
            row = db.execute(
                "SELECT r.*,t.conversation_id,t.type AS task_type,t.owner_id,"
                "c.title AS conversation_title,u.display_name AS owner_name "
                "FROM runs r JOIN tasks t ON t.id=r.task_id "
                "JOIN conversations c ON c.id=t.conversation_id "
                "JOIN users u ON u.id=t.owner_id WHERE r.id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise LookupError("run_not_found")
            run = {**self._run(row), "owner_id": row["owner_id"], "owner_name": row["owner_name"],
                   "conversation_id": row["conversation_id"], "conversation_title": row["conversation_title"],
                   "provider_config_revision": row["provider_config_revision"],
                   "prompt_version": row["prompt_version"], "standard_field_version": row["standard_field_version"]}
            timeline = []
            logs = []
            planned = []
            observed_scopes = set()
            for event in db.execute(
                "SELECT sequence,scope_type,scope_id,event_type,status,summary_json,created_at "
                "FROM run_events WHERE run_id=? ORDER BY sequence", (run_id,)
            ):
                try:
                    summary = json.loads(event["summary_json"])
                except (TypeError, ValueError):
                    summary = {}
                summary = {key: summary[key] for key in PROGRESS_FIELDS if key in summary} if isinstance(summary, dict) else {}
                item = {"sequence": event["sequence"], "scope_type": event["scope_type"],
                        "scope_id": event["scope_id"], "event_type": event["event_type"],
                        "status": event["status"], "summary": summary, "created_at": event["created_at"]}
                timeline.append(item)
                if isinstance(summary.get("planned_steps"), list):
                    planned.extend(summary["planned_steps"])
                if event["scope_type"] == "step":
                    observed_scopes.add(event["scope_id"])
                logs.append({"id": f"event-{event['sequence']}", "level": "error" if event["status"] == "failed" or summary.get("progress_status") == "failed" else "info",
                             "source": "run_event", "run_id": run_id, "task_id": run["task_id"],
                             "scope_id": event["scope_id"], "event_type": event["event_type"],
                             "error_code": None, "created_at": event["created_at"]})
            calls = []
            for call in db.execute(
                "SELECT id,provider,model,error_code,summary_json,created_at "
                "FROM model_calls WHERE run_id=? ORDER BY created_at,id", (run_id,)
            ):
                try:
                    summary = json.loads(call["summary_json"])
                except (TypeError, ValueError):
                    summary = {}
                if not isinstance(summary, dict):
                    summary = {}
                projected = {key: summary[key] for key in (
                    "request_id", "scope_id", "attempt", "duration_ms", "status", "started_at",
                    "finished_at", "http_status", "prompt_version", "standard_field_version",
                    "provider_config_revision", "operation", "input_artifact_id", "input_artifact_version",
                    "skill_id", "tool_id",
                ) if key in summary and isinstance(summary[key], (str, int, float))}
                params = summary.get("params")
                if isinstance(params, dict):
                    projected["params"] = {key: params[key] for key in ("temperature", "top_p", "max_tokens")
                                           if key in params and isinstance(params[key], (int, float)) and not isinstance(params[key], bool)}
                for key in ("request_truncated", "response_truncated"):
                    if type(summary.get(key)) is bool:
                        projected[key] = summary[key]
                if include_content:
                    for key in ("request", "response"):
                        if key in summary:
                            projected[key] = redact_text(summary[key])
                entry = {"id": call["id"], "run_id": run_id, "task_id": run["task_id"],
                         "provider": call["provider"], "model": call["model"],
                         "error_code": call["error_code"], "created_at": call["created_at"], **projected}
                calls.append(entry)
                logs.append({"id": "call-" + call["id"], "level": "error" if call["error_code"] else "info",
                             "source": "model_call", "run_id": run_id, "task_id": run["task_id"],
                             "call_id": call["id"], "scope_id": entry.get("scope_id"),
                             "request_id": entry.get("request_id"), "error_code": call["error_code"],
                             "duration_ms": entry.get("duration_ms"), "created_at": call["created_at"]})
            artifacts = []
            for artifact in db.execute(
                "SELECT id,kind,version,status,sha256,created_at FROM artifacts WHERE run_id=? ORDER BY created_at,id",
                (run_id,),
            ):
                sources = [item[0] for item in db.execute(
                    "SELECT source_artifact_id FROM artifact_edges WHERE derived_artifact_id=? ORDER BY source_artifact_id",
                    (artifact["id"],),
                )]
                artifacts.append({**dict(artifact), "source_artifact_ids": sources})
            failed_call = next((item for item in reversed(calls) if item["error_code"]), None)
            last_call = calls[-1] if calls else None
            possible_call = last_call if run["status"] == "failed" and last_call and last_call["error_code"] else None
            conclusion = {"status": run["status"], "error_code": run["error_code"],
                          "call_id": None, "scope_id": None,
                          "evidence_call_id": failed_call["id"] if failed_call else None,
                          "evidence_scope_id": failed_call.get("scope_id") if failed_call else None,
                          "possible_cause": possible_call["error_code"] if possible_call else None,
                          "category": (run["error_code"] or "未采集") if run["status"] == "failed" else run["status"]}
            if run["status"] == "failed":
                conclusion["reason"] = "具体原因未采集"
            unexecuted = [{**step, "reason": (
                "Run 失败前未启动；具体阻断原因未采集" if run["status"] == "failed"
                else "Run 取消前未启动；具体原因未采集" if run["status"] == "cancelled"
                else "步骤尚未启动；具体原因未采集")}
                          for step in planned if isinstance(step, dict)
                          and step.get("scope_id") not in observed_scopes]
            return {"run": run, "conclusion": conclusion, "evidence_status": "已采集" if calls else "未采集",
                    "timeline": timeline, "planned_steps": planned, "unexecuted_steps": unexecuted,
                    "calls": calls, "logs": logs, "artifacts": artifacts}

    def diagnostic_call(self, run_id, call_id):
        detail = self.diagnostic_run(run_id, include_content=True)
        for call in detail["calls"]:
            if call["id"] == call_id:
                return call
        raise LookupError("model_call_not_found")

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
                self._release_mapping_draft(db,abandoned["id"])
                from .field_changes import FieldChanges
                FieldChanges.release(db, abandoned["id"])
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

    def finish(self, worker_id, claim, error_code=None, message=None, suggestions=None):
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._valid_claim(db, worker_id, claim)
            if row is None:
                db.rollback()
                return False
            if message:
                self._assistant_message(db, row["conversation_id"], message, row["id"], suggestions)
            self._record_state(db, row, "failed" if error_code else "succeeded", error_code)
            db.commit()
            return True

    def _assistant_message(self, db, conversation_id, message, run_id=None, suggestions=None):
        message_id = uid()
        payload = {"text": message, "run_id": run_id}
        if suggestions:
            payload["suggestions"] = suggestions
        db.execute("INSERT INTO messages(id,conversation_id,actor,kind,content_json,created_at) VALUES(?,?,?,?,?,?)",
                   (message_id, conversation_id, "assistant", "text", json.dumps(payload, ensure_ascii=False), now()))
        self._event(db, conversation_id, "message_created", "message", message_id, {"actor": "assistant"})
        return message_id

    OPERATION_LABELS = {"enum_extract": "枚举提取", "threat_mapping": "威胁类型映射", "fill": "填充值映射", "remove_mapping": "取消值映射", "export": "规则导出"}

    def _input_record_message(self, db, conversation_id, kind, payload):
        """按钮/上传的输入留痕：记录用户真实提交的业务动作与参数，不伪造用户文本。"""
        message_id = uid()
        db.execute("INSERT INTO messages(id,conversation_id,actor,kind,content_json,created_at) VALUES(?,?,?,?,?,?)",
                   (message_id, conversation_id, "user", kind, json.dumps(payload, ensure_ascii=False), now()))
        self._event(db, conversation_id, "message_created", "message", message_id, {"actor": "user", "kind": kind})
        return message_id

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
        if terminal and status != "succeeded":
            self._release_mapping_draft(db,row["id"])
            from .field_changes import FieldChanges
            FieldChanges.release(db, row["id"])
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
            if source["task_type"] in {"field_change_apply", "field_change_undo"} or db.execute("SELECT 1 FROM field_change_previews WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError("field_preview_resolution_required")
            frozen_input = json.loads(source["input_snapshot_json"])
            if frozen_input.get("file_id") and not db.execute("SELECT 1 FROM files WHERE id=? AND is_active=1", (frozen_input["file_id"],)).fetchone():
                raise ValueError("business_input_stale")
            if source["status"] not in ("succeeded", "failed", "cancelled"):
                raise ValueError("run_not_retryable")
            current = db.execute("SELECT status FROM runs WHERE id=?", (source["current_run_id"],)).fetchone()
            if current and current["status"] not in ("succeeded", "failed", "cancelled"):
                raise ValueError("task_has_active_run")
            if source["task_type"] == "mapping_draft_apply":
                frozen = json.loads(source["input_snapshot_json"])
                draft = self._owned_draft(db,owner_id,frozen["draft_id"])
                if (draft["status"] != "active" or draft["revision"] != frozen["draft_revision"]
                    or not self._mapping_base_current_db(db,frozen["base_artifact_id"],source["conversation_id"])):
                    raise ValueError("mapping_draft_apply_stale")
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
            if source["task_type"] == "mapping_draft_apply":
                db.execute("UPDATE drafts SET status='applying',apply_run_id=?,updated_at=? WHERE id=?", (new_id,timestamp,snapshot["draft_id"]))
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
            self._admin_audit(db, admin_id, "force_stop", "run", run_id, reason.strip(), before={"status": row["status"]}, after={"status": "cancelled", "error_code": "force_stopped"})
            db.commit()
            return {"id": run_id, "status": "cancelled", "error_code": "force_stopped"}

    def _admin_audit(self, db, admin_id, action, target_type, target_id, reason=None, before=None, after=None):
        """只写白名单字段；reason 与前后状态均为脱敏文本，不落服务器路径、输入快照或密钥。"""
        db.execute("INSERT INTO audit_events(id,actor_id,action,target_type,target_id,created_at,reason,before_json,after_json) VALUES(?,?,?,?,?,?,?,?,?)",
                   (uid(), admin_id, action, target_type, target_id, now(), (reason or "").strip() or None,
                    json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
                    json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None))

    def admin_audit(self, admin_id, action, target_type, target_id, reason=None, before=None, after=None):
        """独立事务记录一次管理写操作；审计失败不回滚已完成的业务写入。"""
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self._admin_audit(db, admin_id, action, target_type, target_id, reason, before, after)
            db.commit()

    def admin_overview(self, admin_id):
        with connect(self.path) as db:
            counts = {row["status"]: row["n"] for row in db.execute("SELECT status,COUNT(*) AS n FROM runs GROUP BY status")}
            lease = db.execute("SELECT owner_id,lease_expires_at,epoch FROM worker_leases WHERE id='v2-primary'").fetchone()
            return {
                "runs": {status: counts.get(status, 0) for status in ("queued", "running", "waiting_confirmation", "cancelling", "succeeded", "failed", "cancelled")},
                "users": db.execute("SELECT COUNT(*) AS n FROM users WHERE is_active=1").fetchone()["n"],
                "conversations": db.execute("SELECT COUNT(*) AS n FROM conversations WHERE archived_at IS NULL").fetchone()["n"],
                "worker": {"lease_owner": lease["owner_id"], "lease_expires_at": lease["lease_expires_at"], "epoch": lease["epoch"]},
            }

    def user_tasks(self, owner_id, status=None, page=1):
        page, size = max(1, int(page)), 50
        where = " WHERE t.owner_id=?" + (" AND t.status=?" if status else "")
        params = [owner_id, *([status] if status else [])]
        with connect(self.path) as db:
            total = db.execute("SELECT COUNT(*) AS n FROM tasks t" + where, params).fetchone()["n"]
            rows = db.execute(
                "SELECT t.id,t.type,t.status,t.current_run_id,t.created_at,t.updated_at,"
                " c.id AS conversation_id,c.title AS conversation_title,r.input_snapshot_json,r.attempt"
                " FROM tasks t JOIN conversations c ON c.id=t.conversation_id"
                " LEFT JOIN runs r ON r.id=t.current_run_id" + where
                + " ORDER BY t.updated_at DESC,t.id DESC LIMIT ? OFFSET ?",
                [*params, size, (page - 1) * size]).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                snapshot = json.loads(item.pop("input_snapshot_json") or "{}")
                item["message_id"] = snapshot.get("message_id")
                item["file_id"] = snapshot.get("file_id")
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": size}

    def user_runs(self, owner_id, status=None, page=1):
        page, size = max(1, int(page)), 50
        where = " WHERE t.owner_id=?" + (" AND r.status=?" if status else "")
        params = [owner_id, *([status] if status else [])]
        join = " FROM runs r JOIN tasks t ON t.id=r.task_id JOIN conversations c ON c.id=t.conversation_id"
        with connect(self.path) as db:
            total = db.execute("SELECT COUNT(*) AS n" + join + where, params).fetchone()["n"]
            rows = db.execute(
                "SELECT r.*,t.conversation_id,t.type AS task_type,c.title AS conversation_title"
                + join + where + " ORDER BY r.updated_at DESC,r.id DESC LIMIT ? OFFSET ?",
                [*params, size, (page - 1) * size]).fetchall()
            return {"items": [{**self._run(row), "conversation_id": row["conversation_id"],
                               "conversation_title": row["conversation_title"]} for row in rows],
                    "total": total, "page": page, "page_size": size}

    def admin_runs(self, admin_id, status=None, page=1):
        page = max(1, int(page))
        size = 50
        where, params = (" WHERE r.status=?", [status]) if status else ("", [])
        with connect(self.path) as db:
            total = db.execute("SELECT COUNT(*) AS n FROM runs r" + where, params).fetchone()["n"]
            rows = db.execute(
                "SELECT r.*,t.conversation_id,t.type AS task_type,t.owner_id,c.title AS conversation_title,u.display_name AS owner_name"
                " FROM runs r JOIN tasks t ON t.id=r.task_id JOIN conversations c ON c.id=t.conversation_id JOIN users u ON u.id=t.owner_id"
                + where + " ORDER BY r.updated_at DESC,r.id DESC LIMIT ? OFFSET ?", [*params, size, (page - 1) * size]).fetchall()
            return {"items": [{**self._run(row), "owner_id": row["owner_id"], "owner_name": row["owner_name"], "conversation_id": row["conversation_id"], "conversation_title": row["conversation_title"]} for row in rows], "total": total, "page": page, "page_size": size}

    def admin_cancel_queued(self, admin_id, run_id, reason=None):
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?", (run_id,)).fetchone()
            if row is None:
                raise LookupError("run_not_found")
            if row["status"] != "queued":
                raise ValueError("run_not_queued")
            self._record_state(db, row, "cancelled", "cancelled_by_admin")
            self._admin_audit(db, admin_id, "cancel_queued", "run", run_id, reason, before={"status": "queued"}, after={"status": "cancelled", "error_code": "cancelled_by_admin"})
            db.commit()
            return {"id": run_id, "status": "cancelled", "error_code": "cancelled_by_admin"}

    def admin_audit_events(self, admin_id, page=1):
        page = max(1, int(page))
        size = 50
        with connect(self.path) as db:
            total = db.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()["n"]
            rows = db.execute(
                "SELECT a.id,a.action,a.target_type,a.target_id,a.created_at,a.reason,a.before_json,a.after_json,u.display_name AS actor_name"
                " FROM audit_events a JOIN users u ON u.id=a.actor_id ORDER BY a.created_at DESC,a.id DESC LIMIT ? OFFSET ?", (size, (page - 1) * size)).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["before"] = json.loads(item.pop("before_json")) if item["before_json"] else None
                item["after"] = json.loads(item.pop("after_json")) if item["after_json"] else None
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": size}

    def _master_key(self):
        from toolwithagent_v2.infrastructure.providers import MasterKeyUnavailable, resolve_master_key
        if self._cached_master_key is None:
            key = resolve_master_key(self.root, development=self.settings.development)
            if key is None:
                raise MasterKeyUnavailable("master_key_missing")
            self._cached_master_key = key
        return self._cached_master_key

    def admin_providers(self, admin_id):
        from toolwithagent_v2.infrastructure.providers import PROVIDER_BASE_URLS, provider_label
        with connect(self.path) as db:
            current = {row["provider"]: dict(row) for row in db.execute(
                "SELECT p.provider,p.current_revision,c.model,c.created_at FROM provider_configs p"
                " LEFT JOIN provider_config_versions c ON c.provider=p.provider AND c.revision=p.current_revision")}
            secrets = {row["provider"] for row in db.execute("SELECT DISTINCT provider FROM provider_config_versions WHERE secret_version_id IS NOT NULL")}
        return {"items": [{"provider": name, "label": provider_label(name), "base_url": PROVIDER_BASE_URLS[name],
                           "revision": (current.get(name) or {}).get("current_revision") or 0,
                           "model": (current.get(name) or {}).get("model") if name in current else None,
                           "updated_at": (current.get(name) or {}).get("created_at") if name in current else None,
                           "has_secret": name in secrets} for name in PROVIDER_BASE_URLS]}

    def admin_save_provider(self, admin_id, provider, model, api_key, params=None, reason=None):
        from toolwithagent_v2.infrastructure.providers import PROVIDER_BASE_URLS, seal_secret
        if provider not in PROVIDER_BASE_URLS:
            raise LookupError("provider_not_found")
        model = (model or "").strip()
        if not model or len(model) > 160 or not api_key or len(api_key) > 4096:
            raise ValueError("invalid_provider_input")
        if params is not None and (not isinstance(params, dict) or len(json.dumps(params)) > 4000):
            raise ValueError("invalid_provider_input")
        params = params or {}
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT current_revision FROM provider_configs WHERE provider=?", (provider,)).fetchone()
            previous = row["current_revision"] if row else 0
            sealed = seal_secret(self._master_key(), api_key)
            secret_id = uid()
            db.execute("INSERT INTO provider_secrets(id,ciphertext,nonce,key_id,created_at) VALUES(?,?,?,?,?)",
                       (secret_id, sealed["blob"], sealed["blob"][:16], sealed["key_id"], now()))
            revision = previous + 1
            db.execute("INSERT INTO provider_config_versions(id,provider,model,params_json,secret_version_id,revision,created_at) VALUES(?,?,?,?,?,?,?)",
                       (uid(), provider, model, json.dumps(params, ensure_ascii=False, sort_keys=True), secret_id, revision, now()))
            if row is None:
                db.execute("INSERT INTO provider_configs(provider,current_revision,created_at) VALUES(?,?,?)", (provider, revision, now()))
            else:
                db.execute("UPDATE provider_configs SET current_revision=? WHERE provider=?", (revision, provider))
            self._admin_audit(db, admin_id, "provider_update", "provider", provider, reason,
                              before={"revision": previous}, after={"revision": revision, "model": model})
            db.commit()
            return {"provider": provider, "revision": revision, "model": model}

    def admin_provider_history(self, admin_id, provider):
        from toolwithagent_v2.infrastructure.providers import PROVIDER_BASE_URLS
        if provider not in PROVIDER_BASE_URLS:
            raise LookupError("provider_not_found")
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT revision,model,params_json,created_at,secret_version_id FROM provider_config_versions WHERE provider=? ORDER BY revision DESC",
                (provider,)).fetchall()
        return {"items": [{"revision": row["revision"], "model": row["model"],
                           "params": json.loads(row["params_json"]), "created_at": row["created_at"],
                           "has_secret": row["secret_version_id"] is not None} for row in rows]}

    def resolve_provider_secret(self, provider, revision=None):
        """Frozen-run read path: decrypt the exact stored version, never the latest by default."""
        master = self._master_key()
        with connect(self.path) as db:
            if revision is None:
                row = db.execute(
                    "SELECT v.model,v.params_json,v.secret_version_id FROM provider_configs p"
                    " JOIN provider_config_versions v ON v.provider=p.provider AND v.revision=p.current_revision WHERE p.provider=?",
                    (provider,)).fetchone()
            else:
                row = db.execute(
                    "SELECT model,params_json,secret_version_id FROM provider_config_versions WHERE provider=? AND revision=?",
                    (provider, revision)).fetchone()
            if row is None or row["secret_version_id"] is None:
                raise LookupError("provider_not_found")
            sealed = db.execute("SELECT ciphertext FROM provider_secrets WHERE id=?", (row["secret_version_id"],)).fetchone()
        from toolwithagent_v2.infrastructure.providers import open_secret
        return {"model": row["model"], "params": json.loads(row["params_json"]),
                "api_key": open_secret(master, sealed["ciphertext"])}

    def admin_test_provider(self, admin_id, provider, model=None, api_key=None, params=None):
        """Live connection probe; never creates a Task or Run, never logs the key."""
        import httpx
        from toolwithagent_v2.infrastructure.providers import PROVIDER_BASE_URLS
        if provider not in PROVIDER_BASE_URLS:
            raise LookupError("provider_not_found")
        base_url = (params or {}).get("base_url") or PROVIDER_BASE_URLS[provider]
        if not api_key:
            saved = self.resolve_provider_secret(provider)
            api_key = saved["api_key"]
            model = model or saved["model"]
        started = time.monotonic()
        try:
            with httpx.Client(trust_env=False, timeout=8) as client:
                response = client.get(base_url.rstrip("/") + "/models", headers={"Authorization": "Bearer " + api_key})
            latency = int((time.monotonic() - started) * 1000)
            return {"ok": response.status_code == 200, "status_code": response.status_code, "latency_ms": latency}
        except httpx.HTTPError as exc:
            latency = int((time.monotonic() - started) * 1000)
            return {"ok": False, "status_code": None, "latency_ms": latency, "error": type(exc).__name__}

    def admin_users(self, admin_id):
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT u.id,u.display_name,u.role,u.is_active,u.created_at,"
                "(SELECT COUNT(*) FROM conversations c WHERE c.owner_id=u.id AND c.archived_at IS NULL) AS conversations"
                " FROM users u ORDER BY u.id").fetchall()
        return {"items": [{"id": row["id"], "display_name": row["display_name"], "role": row["role"],
                           "active": bool(row["is_active"]), "created_at": row["created_at"],
                           "conversations": row["conversations"]} for row in rows]}

    def admin_set_role(self, admin_id, user_id, role, reason=None):
        if role not in ("user", "developer", "admin"):
            raise ValueError("invalid_role")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,role FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
            if row is None:
                raise LookupError("user_not_found")
            if row["role"] == role:
                raise ValueError("role_unchanged")
            if user_id == admin_id:
                raise ValueError("cannot_change_own_role")
            db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            self._admin_audit(db, admin_id, "user_role_change", "user", user_id, reason,
                              before={"role": row["role"]}, after={"role": role})
            db.commit()
            return {"id": user_id, "role": role}

    def admin_set_active(self, admin_id, user_id, active, reason=None):
        if not isinstance(active, bool):
            raise ValueError("invalid_active")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,is_active FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise LookupError("user_not_found")
            if bool(row["is_active"]) == active:
                raise ValueError("active_unchanged")
            if user_id == admin_id and not active:
                raise ValueError("cannot_deactivate_self")
            db.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))
            self._admin_audit(db, admin_id, "user_active_change", "user", user_id, reason,
                              before={"active": bool(row["is_active"])}, after={"active": active})
            db.commit()
            return {"id": user_id, "active": active}

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
            if claim["input"].get("business_inputs") and not self._business_current_db(db, claim):
                self._record_state(db, row, "failed", "business_input_stale")
                db.commit()
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

    def confirm(self, owner_id, run_id, token, checkpoint_revision, idempotency_key=None):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned_run(db, owner_id, run_id)
            scope = "confirmation:" + run_id
            request_digest, receipt = self._draft_receipt(db, owner_id, scope, idempotency_key, [digest, checkpoint_revision]) if idempotency_key else (None, None)
            if receipt is not None:
                return receipt
            if row["current_run_id"] != run_id or row["status"] != "waiting_confirmation":
                raise ValueError("run_not_waiting")
            if db.execute("SELECT 1 FROM field_change_previews WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError("field_preview_resolution_required")
            frozen = json.loads(row["input_snapshot_json"])
            if frozen.get("business_inputs") and not self._business_current_db(db, {"conversation_id": row["conversation_id"], "input": frozen}):
                raise ValueError("continuation_stale")
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
            result = {"id": run_id, "status": "queued"}
            if idempotency_key:
                self._save_draft_receipt(db, owner_id, scope, idempotency_key, request_digest, result)
            db.commit()
            return result

    def continuation(self, run_id):
        from application.execution_continuation import ExecutionContinuation
        with connect(self.path) as db:
            row = db.execute("SELECT continuation_json FROM execution_checkpoints WHERE run_id=? ORDER BY revision DESC LIMIT 1", (run_id,)).fetchone()
            return ExecutionContinuation.from_json(row["continuation_json"]) if row else None

    def publish(self, worker_id, claim, content: bytes, kind="fake_result", metadata=None, message=None, suggestions=None):
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
                if kind == "field_mapping":
                    applying = claim["task_type"] == "mapping_draft_apply"
                    valid = (self._draft_apply_current_db(db,claim) if applying else
                             self._mapping_is_current_db(db,claim) and claim["input"].get("mapping_edit_anchor") == self._mapping_edit_anchor(db,row["conversation_id"]))
                    if not valid:
                        self._assistant_message(db,row["conversation_id"],"映射来源或草稿版本已变化，请重新查看结果",row["id"])
                        self._record_state(db,row,"failed","mapping_draft_apply_stale" if applying else "mapping_input_stale")
                        db.commit()
                        return True
                    if applying:
                        self._owned_mapping(claim["owner_id"],claim["input"]["base_artifact_id"])
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage, final)
                # The rename is short, but fail closed if the lease expired while
                # the database lock was held.
                if self._valid_claim(db, worker_id, claim) is None:
                    db.rollback()
                    return False
                if kind == "field_mapping":
                    version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM artifacts WHERE conversation_id=? AND kind=?", (row["conversation_id"],kind)).fetchone()[0]
                    previous = [item["id"] for item in db.execute("SELECT id FROM artifacts WHERE conversation_id=? AND kind='field_mapping' AND status='published'", (row["conversation_id"],))]
                    for previous_id in previous:
                        db.execute("WITH RECURSIVE descendants(id) AS (SELECT ? UNION SELECT edge.derived_artifact_id FROM artifact_edges edge JOIN descendants d ON edge.source_artifact_id=d.id) UPDATE artifacts SET status='stale' WHERE id IN (SELECT id FROM descendants)", (previous_id,))
                else:
                    version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM artifacts WHERE task_id=? AND kind=?", (row["task_id"],kind)).fetchone()[0]
                artifact_id = uid()
                metadata = dict(metadata or {})
                if message:
                    # 建议里的产物占位（artifact_id/classification_artifact_id 为 None）回填为本轮产物 ID。
                    filled = [{**item, **{key: artifact_id for key in ("artifact_id", "classification_artifact_id")
                                          if key in item and item[key] is None}}
                              for item in (suggestions or [])] or None
                    metadata["result_message_id"] = self._assistant_message(db, row["conversation_id"], message, row["id"], filled)
                db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (artifact_id, row["conversation_id"], row["task_id"], row["id"], kind, version, "published", key, sha, json.dumps(metadata or {}, ensure_ascii=False), now(), len(content)))
                if kind == "field_mapping" and claim["input"].get("source_artifact_id"):
                    db.execute("INSERT INTO artifact_edges(source_artifact_id,derived_artifact_id,relation) VALUES(?,?,?)", (claim["input"]["source_artifact_id"],artifact_id,"field_mapping"))
                if kind == "field_mapping" and claim["task_type"] == "mapping_draft_apply":
                    db.execute("INSERT INTO artifact_edges(source_artifact_id,derived_artifact_id,relation) VALUES(?,?,'mapping_edit')", (claim["input"]["base_artifact_id"],artifact_id))
                    db.execute("INSERT OR IGNORE INTO artifact_edges(source_artifact_id,derived_artifact_id,relation) SELECT source_artifact_id,?,relation FROM artifact_edges WHERE derived_artifact_id=?", (artifact_id,claim["input"]["base_artifact_id"]))
                    db.execute("UPDATE drafts SET status='applied',updated_at=? WHERE id=? AND apply_run_id=?", (now(),claim["input"]["draft_id"],row["id"]))
                self._event(db, row["conversation_id"], "artifact_published", "artifact", artifact_id,
                            {"artifact_id": artifact_id, "run_id": row["id"], "kind": kind, "version": version})
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
                    self._assistant_message(db, row["conversation_id"], "主数据或分类结果已变化，请重新提取", row["id"])
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
                    self._assistant_message(db, row["conversation_id"], "知识申请未提交，请检查结果后重试", row["id"])
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
                self._assistant_message(db, row["conversation_id"], "日志知识申请已处理", row["id"])
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


    def _business_command_guard(self, db, owner_id, conversation_id):
        """未应用 Draft 或待确认方案必须先明确处理。"""
        if db.execute("SELECT 1 FROM field_change_previews WHERE conversation_id=? AND status IN ('ready','applying')", (conversation_id,)).fetchone():
            raise ValueError("field_preview_resolution_required")
        if db.execute("SELECT 1 FROM drafts WHERE conversation_id=? AND owner_id=? AND status IN ('active','applying') AND changed_count>0", (conversation_id, owner_id)).fetchone():
            raise ValueError("draft_resolution_required")
        if db.execute("SELECT 1 FROM runs r JOIN tasks t ON t.id=r.task_id WHERE t.conversation_id=? AND r.status='waiting_confirmation'", (conversation_id,)).fetchone():
            raise ValueError("confirmation_resolution_required")

    def _freeze_business(self, db, conversation_id):
        """固定主数据、所有附件和唯一兼容类型化产物的身份与哈希。"""
        file, classification = self._current_mapping_input(db, conversation_id)
        snapshot = {key: file[key] for key in ("sha256", "storage_key", "media_type", "original_name")} if file else {}
        snapshot["file_id"] = file["id"] if file else None
        attachments = [dict(row) for row in db.execute("SELECT id,sha256,storage_key,media_type,original_name FROM files WHERE conversation_id=? AND role='enum_mapping' AND is_active=1 AND parse_status='succeeded' AND created_at>=? ORDER BY created_at,id", (conversation_id, file["created_at"] if file else "9999"))]
        snapshot["classification_anchor"] = classification["id"] if classification else None
        refs = {}
        if file:
            for row in db.execute("SELECT a.id,a.sha256,a.storage_key,a.kind FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.conversation_id=? AND a.status='published' AND a.kind IN ('field_mapping','log_classification','enum_values','threat_mapping','business_state') AND json_extract(r.input_snapshot_json,'$.file_id')=? ORDER BY a.created_at,a.id", (conversation_id, file["id"])):
                if row["kind"] == "field_mapping":
                    source = db.execute("SELECT input_snapshot_json FROM runs WHERE id=(SELECT run_id FROM artifacts WHERE id=?)", (row["id"],)).fetchone()
                    if json.loads(source[0]).get("classification_anchor") != snapshot["classification_anchor"]:
                        continue
                refs[row["kind"]] = dict(row)
        snapshot["classification_anchor"] = classification["id"] if classification else None
        snapshot["business_inputs"] = {"primary": {"id": snapshot["file_id"], "sha256": snapshot.get("sha256")}, "attachments": attachments, "refs": refs}
        return snapshot

    def _business_current_db(self, db, claim):
        """发布和确认重查真实版本，安全事实计数相同也不能放过内容变化。"""
        current = self._freeze_business(db, claim["conversation_id"])
        frozen = claim["input"].get("business_inputs")
        if frozen != current["business_inputs"]:
            return False
        if claim["input"].get("file_id"):
            try:
                self._read_blob(claim["input"], "uploads")
            except ValueError:
                return False
        for reference in [*frozen["attachments"], *frozen["refs"].values()]:
            try:
                self._read_blob(reference, "uploads" if reference in frozen["attachments"] else "artifacts")
            except ValueError:
                return False
        return True

    def business_is_current(self, claim):
        with connect(self.path) as db:
            return self._business_current_db(db, claim)

    def enqueue_operation(self, owner_id, conversation_id, step, source_artifact_id=None, config_artifact_id=None, idempotency_key=None):
        """按钮只接受完整 StepSpec；结果卡 ID 必须匹配当前显式来源。"""
        from contracts.planner_models import DeterministicPlan
        if step.depends_on or getattr(step, "source_ref", "").startswith("step:"):
            raise ValueError("button_dependencies_forbidden")
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self.owns(db, conversation_id, owner_id)
            scope = "operation:" + conversation_id
            request = [step.model_dump(mode="json"), source_artifact_id, config_artifact_id]
            digest, receipt = self._draft_receipt(db, owner_id, scope, idempotency_key, request) if idempotency_key else (None, None)
            if receipt is not None:
                return receipt
            self._business_command_guard(db, owner_id, conversation_id)
            snapshot = self._freeze_business(db, conversation_id)
            refs = snapshot["business_inputs"]["refs"]
            source = getattr(step, "source_ref", None)
            kind = {"session.artifacts.enum_values": "enum_values", "session.artifacts.threat_mapping": "threat_mapping", "session.log_classification.entry_rules": "log_classification", "session.log_classification.sub_rules": "log_classification"}.get(source)
            if source_artifact_id and (not kind or refs.get(kind, {}).get("id") != source_artifact_id):
                raise ValueError("artifact_source_stale")
            if config_artifact_id and refs.get("field_mapping", {}).get("id") != config_artifact_id:
                raise ValueError("config_source_stale")
            plan = DeterministicPlan(plan_id=uid(), steps=(step,))
            snapshot["plan"] = plan.model_dump(mode="json")
            label = self.OPERATION_LABELS.get(step.type, "业务操作")
            message_id = self._input_record_message(db, conversation_id, "operation",
                {"text": f"提交{label}", "action": step.type, "step": step.model_dump(mode="json"),
                 "source_artifact_id": source_artifact_id, "config_artifact_id": config_artifact_id})
            snapshot["message_id"] = message_id
            result = self._enqueue_task(db, owner_id, conversation_id, "business_operation", snapshot)
            result["message"] = {"id": message_id, "kind": "operation"}
            if idempotency_key:
                self._save_draft_receipt(db, owner_id, scope, idempotency_key, digest, result)
            db.commit()
            return result

    def _read_blob(self, reference, directory="artifacts"):
        """固定目录与 SHA 校验用于所有输入和本人内容接口。"""
        key = reference["storage_key"]
        if not isinstance(key, str) or not key.startswith(directory + "/") or ".." in key.split("/"):
            raise ValueError("artifact_corrupt")
        path = (self.root / key).resolve()
        if not path.is_relative_to((self.root / directory).resolve()):
            raise ValueError("artifact_corrupt")
        try:
            content = path.read_bytes()
        except OSError:
            raise ValueError("artifact_corrupt") from None
        if hashlib.sha256(content).hexdigest() != reference["sha256"]:
            raise ValueError("artifact_corrupt")
        return content

    def read_business_session(self, claim, *, summary_only=False):
        """从冻结 Blob 重建内存副本，真实值不进入 SessionFacts 或事件投影。"""
        from toolwithagent_v2.runtime.postprocessing import BusinessSession, primary_session, restore_session, attach_enum, configuration_root
        snapshot = claim["input"]
        refs = snapshot["business_inputs"]["refs"]
        state = json.loads(self._read_blob(refs["business_state"])) if "business_state" in refs else None
        # Page controls need log presence; execution keeps the complete input.
        log_limit = 1 if summary_only else None
        session = restore_session(state, log_limit=log_limit) if state else (primary_session(self.root / snapshot["storage_key"], snapshot, log_limit=log_limit) if snapshot["file_id"] else BusinessSession())
        base = json.loads(self._read_blob(refs["field_mapping"])) if "field_mapping" in refs else None
        if base:
            source = base.get("configuration_source", "session.mapped_sub_rules")
            if source == "session.decoded_config":
                session.decoded_data = configuration_root(base)
            else:
                session.mapped_sub_rules = configuration_root(base)
            with connect(self.path) as db:
                previous = db.execute("SELECT input_snapshot_json FROM runs WHERE id=(SELECT run_id FROM artifacts WHERE id=?)", (refs["field_mapping"]["id"],)).fetchone()
                fields = json.loads(previous[0]).get("source_fields")
            if fields:
                from contracts.rule_source import RuleSourceFields
                session.rule_source_fields = RuleSourceFields.from_value(fields)
        if "log_classification" in refs:
            classification = json.loads(self._read_blob(refs["log_classification"]))["classification"]
            if base is None and session.log_classification != classification:
                from application.session_state import commit_log_classification
                commit_log_classification(session, classification)
            else:
                session.log_classification = classification
        from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
        for kind, key, model in (("enum_values", "latest_enum_artifact", EnumArtifactSlot), ("threat_mapping", "latest_threat_artifact", ThreatArtifactSlot)):
            if kind not in refs:
                setattr(session, key, None)
            else:
                artifact = json.loads(self._read_blob(refs[kind]))
                slot = model.model_validate({"artifact": artifact, "source_field": artifact.get("field") if kind == "enum_values" else artifact.get("source_field")})
                if kind == "enum_values":
                    session.latest_enum_artifact = slot
                else:
                    session.latest_threat_artifact = slot
        applied = set(session.applied_attachment_ids)
        for attachment in snapshot["business_inputs"]["attachments"]:
            self._read_blob(attachment, "uploads")
            if attachment["id"] not in applied:
                attach_enum(session, self.root / attachment["storage_key"], self.root / "staging")
                applied.add(attachment["id"])
        session.applied_attachment_ids = sorted(applied)
        return session, base

    def artifact_content(self, owner_id, artifact_id):
        with connect(self.path) as db:
            row = db.execute("SELECT a.* FROM artifacts a JOIN tasks t ON t.id=a.task_id WHERE a.id=? AND t.owner_id=? AND a.kind IN ('field_mapping','log_classification','enum_values','threat_mapping','config_export') AND a.status IN ('published','stale')", (artifact_id, owner_id)).fetchone()
            if row is None:
                raise LookupError("artifact_not_found")
        return json.loads(self._read_blob(row))

    def artifact_download(self, owner_id, artifact_id):
        from contracts.download_naming import download_filename
        from io import BytesIO
        from openpyxl import Workbook
        payload = self.artifact_content(owner_id, artifact_id)
        with connect(self.path) as db:
            row = db.execute("SELECT kind,created_at FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        kind = row["kind"]
        timestamp = datetime.fromisoformat(row["created_at"]).strftime("%Y%m%d_%H%M%S")
        if kind == "field_mapping":
            name, content = self.mapping_download(owner_id, artifact_id)
            media = "text/plain; charset=utf-8"
        elif kind == "config_export":
            name, content, media = download_filename(payload["download_kind"], timestamp), payload["content"].encode("utf-8"), "text/plain; charset=utf-8"
        elif kind == "threat_mapping":
            workbook = Workbook(); sheet = workbook.active; sheet.title = "threat_mapping"
            sheet.append(["mappingType", "orgValue", "mappingValue"])
            for item in payload["mappings"]:
                sheet.append([item["mapping_type"], item["original_value"], item["mapped_value"]])
            output = BytesIO(); workbook.save(output); workbook.close()
            name, content, media = download_filename(kind, timestamp), output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            downloadable = ({"field": payload["field"], "regex": payload["regex"], "original_log": payload["original_log"], "value": payload["values"]}
                            if kind == "enum_values" else payload["classification"])
            name, content, media = download_filename(kind, timestamp), json.dumps(downloadable, ensure_ascii=False, indent=4).encode("utf-8"), "application/json; charset=utf-8"
        with connect(self.path) as db:
            db.execute("INSERT INTO audit_events(id,actor_id,action,target_type,target_id,created_at,reason) VALUES(?,?,?,?,?,?,?)", (uid(), owner_id, "artifact_download", "artifact", artifact_id, now(), ""))
        return name, content, media

    def _cancel_business_runs(self, db, conversation_id, exclude_run_id=None):
        """显式清空取消旧运行及令牌，保留消息、草稿和产物历史。"""
        rows = db.execute("SELECT r.*,t.conversation_id,t.type AS task_type FROM runs r JOIN tasks t ON t.id=r.task_id WHERE t.conversation_id=? AND r.status IN ('queued','running','waiting_confirmation')", (conversation_id,)).fetchall()
        for row in rows:
            if row["id"] == exclude_run_id:
                continue
            db.execute("UPDATE confirmations SET status='superseded',rotated_at=? WHERE run_id=? AND status='pending'", (now(), row["id"]))
            self._record_state(db, row, "cancelled", "business_cleared")

    def clear_business(self, worker_id, claim):
        """在领取 fence 的同一事务中清空业务输入，历史 Blob 保持本人可读。"""
        from application.request_runtime import clear_session_data
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._valid_claim(db, worker_id, claim)
            if row is None:
                return False
            boundary = claim["input"]["clear_boundary"]
            # 只清理安全的生命周期引用，不读取或解析即将作废的业务 Blob。
            from toolwithagent_v2.runtime.postprocessing import BusinessSession
            lifecycle = BusinessSession(applied_attachment_ids=list(boundary["file_ids"]))
            clear_session_data(lifecycle)
            for file_id in boundary["file_ids"]:
                db.execute("UPDATE files SET is_active=0 WHERE id=? AND conversation_id=?", (file_id, row["conversation_id"]))
            for artifact_id in boundary["artifact_ids"]:
                db.execute("UPDATE artifacts SET status='stale' WHERE id=? AND conversation_id=? AND status='published'", (artifact_id, row["conversation_id"]))
                db.execute("UPDATE drafts SET status='discarded',updated_at=?,revision=revision+1 WHERE base_artifact_id=? AND conversation_id=? AND status IN ('active','applying')", (now(), artifact_id, row["conversation_id"]))
            for run_id in boundary["run_ids"]:
                db.execute("DELETE FROM execution_checkpoints WHERE run_id=?", (run_id,))
            if self._valid_claim(db, worker_id, claim) is None:
                db.rollback()
                return False
            self._assistant_message(db, row["conversation_id"], "业务数据已清空，历史结果仍可查看和下载。", row["id"])
            self._event(db, row["conversation_id"], "business_cleared", "run", row["id"], {"run_id": row["id"]})
            self._record_state(db, row, "succeeded")
            db.commit()
            return True

    def publish_business(self, worker_id, claim, artifacts, message=None, suggestions=None):
        """同一事务发布本次全部产物、血缘、消息与 outbox，拒绝迟到写入。"""
        staged = []
        try:
            for artifact in artifacts:
                content = json.dumps(artifact["payload"], ensure_ascii=False).encode("utf-8")
                sha = hashlib.sha256(content).hexdigest(); key = f"artifacts/{sha[:2]}/{sha}"
                stage = self.root / "staging" / (uid() + ".stage")
                with stage.open("wb") as handle:
                    handle.write(content); handle.flush(); os.fsync(handle.fileno())
                if hashlib.sha256(stage.read_bytes()).hexdigest() != sha:
                    raise ValueError("staging_hash_mismatch")
                staged.append((artifact, content, sha, key, stage))
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._valid_claim(db, worker_id, claim)
                if row is None:
                    return False
                if claim["input"].get("business_inputs") and not self._business_current_db(db, claim):
                    self._record_state(db, row, "failed", "business_input_stale")
                    self._assistant_message(db, row["conversation_id"], "输入或配置版本已变化，请重新发起操作。", row["id"])
                    db.commit(); return True
                result_message_id = self._assistant_message(db, row["conversation_id"], message, row["id"], suggestions) if message else None
                # Stale old versions and their descendants before inserting this transaction's outputs.
                for replacing_kind in {item[0]["kind"] for item in staged} - {"business_state"}:
                    previous = db.execute("SELECT id FROM artifacts WHERE conversation_id=? AND kind=? AND status='published'", (row["conversation_id"], replacing_kind)).fetchall()
                    for old in previous:
                        db.execute("WITH RECURSIVE descendants(id) AS (SELECT ? UNION SELECT e.derived_artifact_id FROM artifact_edges e JOIN descendants d ON e.source_artifact_id=d.id) UPDATE artifacts SET status='stale' WHERE id IN (SELECT id FROM descendants) AND status='published'", (old["id"],))
                created = {}
                for artifact, content, sha, key, stage in staged:
                    final = self.root / key; final.parent.mkdir(parents=True, exist_ok=True); os.replace(stage, final)
                    kind = artifact["kind"]; payload = artifact["payload"]
                    version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM artifacts WHERE conversation_id=? AND kind=?", (row["conversation_id"], kind)).fetchone()[0]
                    db.execute("UPDATE artifacts SET status='stale' WHERE conversation_id=? AND kind=? AND status='published'", (row["conversation_id"], kind))
                    artifact_id = uid()
                    created[kind] = artifact_id
                    summary = {"item_count": payload.get("item_count", 0)}
                    if kind == "log_classification":
                        from toolwithagent_v2.runtime.worker import Worker
                        summary = Worker._summary(payload, payload["total_lines"])
                    if kind == "field_mapping":
                        from toolwithagent_v2.runtime.mapping_projection import mapping_summary
                        summary = mapping_summary(payload)
                    metadata = {"summary": summary, "submission_eligible": bool(payload.get("submission_eligible")), "config_ref": payload.get("configuration_source", "session.mapped_sub_rules") if kind == "field_mapping" else None, "field_change_run_id": payload.get("field_change_run_id"), "undo_of": payload.get("undo_of"), "source_field": payload.get("field", payload.get("source_field")), "message_id": claim["input"].get("message_id"), "result_message_id": result_message_id}
                    db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (artifact_id, row["conversation_id"], row["task_id"], row["id"], kind, version, "published", key, sha, json.dumps(metadata, ensure_ascii=False), now(), len(content)))
                    for source in claim["input"].get("business_inputs", {}).get("refs", {}).values():
                        if kind == "config_export" and "field_mapping" in created and source["kind"] == "field_mapping":
                            continue  # 导出绑定本轮新配置，旧配置仍是新配置的输入血缘。
                        db.execute("INSERT OR IGNORE INTO artifact_edges(source_artifact_id,derived_artifact_id,relation) VALUES(?,?,?)", (source["id"], artifact_id, kind))
                    self._event(db, row["conversation_id"], "artifact_published", "artifact", artifact_id, {"artifact_id": artifact_id, "run_id": row["id"], "kind": kind, "version": version})
                for artifact in artifacts:
                    for source_kind in artifact.get("source_kinds", ()):
                        if source_kind in created and source_kind != artifact["kind"]:
                            db.execute("INSERT OR IGNORE INTO artifact_edges(source_artifact_id,derived_artifact_id,relation) VALUES(?,?,?)", (created[source_kind], created[artifact["kind"]], artifact["kind"]))
                if "config_export" in created and "field_mapping" in created:
                    db.execute("INSERT OR IGNORE INTO artifact_edges(source_artifact_id,derived_artifact_id,relation) VALUES(?,?,?)", (created["field_mapping"], created["config_export"], "config_export"))
                if self._valid_claim(db, worker_id, claim) is None:
                    return False
                from .field_changes import FieldChanges
                FieldChanges(self).published(db, claim, created)
                self._record_state(db, row, "succeeded")
                db.commit(); return True
        finally:
            for _, _, _, _, stage in staged:
                stage.unlink(missing_ok=True)


    def _conversation_facts(self, db, owner_id, conversation_id):
        """复用安全事实投影供按钮点名；内容损坏明确禁用，不冒充空会话。"""
        from application.log_privacy import private_business_logging
        from application.session_projection import build_session_facts
        snapshot = self._freeze_business(db, conversation_id)
        try:
            if snapshot.get("file_id"):
                self._read_blob(snapshot, "uploads")
            with private_business_logging():
                session, _ = self.read_business_session({"owner_id": owner_id, "conversation_id": conversation_id, "input": snapshot}, summary_only=True)
                full = build_session_facts(session, include_field_pools=False).model_dump(mode="json")
                facts = {key: full[key] for key in ("has_logs", "has_log_classification", "has_decoded_config", "available_config_refs", "enum_mapping_target_fields", "enum_mapping_row_count", "mapped_sub_rule_count", "referenceable_artifacts")}
            return {"session_facts": facts, "session_facts_error": None}
        except (ValueError, LookupError, OSError, KeyError, TypeError):
            return {"session_facts": None, "session_facts_error": "business_input_unavailable"}


    def record_progress(self, worker_id, claim, scope_id, summary):
        """在写锁内验证当前发布资格，只记录 V2 sink 的安全白名单。"""
        safe = {key: summary[key] for key in PROGRESS_FIELDS if key in summary}
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._valid_claim(db, worker_id, claim)
            if row is None:
                return False
            sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM run_events WHERE run_id=?", (claim["id"],)).fetchone()[0]
            db.execute("INSERT INTO run_events(id,run_id,sequence,scope_type,scope_id,event_type,status,summary_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (uid(), claim["id"], sequence, "step", scope_id, "run_progress", "running", json.dumps(safe, separators=(",", ":")), now()))
            self._event(db, row["conversation_id"], "run_progress", "run", claim["id"], {"run_id": claim["id"], "status": "running", "scope_id": scope_id, **safe})
            db.commit()
            return True

    def record_model_call(self, worker_id, claim, event):
        """Persist bounded evidence only while this Worker still owns the Run."""
        allowed_errors = {"model_connection", "model_timeout", "model_authentication", "model_rate_limited",
                          "provider_unavailable", "model_unavailable", "model_response_format",
                          "provider_request_failed", "model_unclassified"}
        error_code = event.get("error_code")
        if error_code not in allowed_errors:
            error_code = "model_unclassified" if error_code else None
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._valid_claim(db, worker_id, claim)
            if row is None:
                return False
            attempt = event.get("attempt")
            if not isinstance(attempt, int) or attempt < 1:
                attempt = 1
            summary = {key: event[key] for key in (
                "request_id", "scope_id", "started_at", "finished_at", "duration_ms", "status", "http_status",
            ) if key in event and isinstance(event[key], (str, int, float))}
            summary["attempt"] = attempt
            skill_id = event.get("skill_id")
            if isinstance(skill_id, str) and re.fullmatch(r"skills/[a-z0-9-]{1,64}", skill_id):
                summary["skill_id"] = skill_id
            tool_id = event.get("tool_id")
            if isinstance(tool_id, str) and re.fullmatch(r"[a-z][a-z0-9_.]{1,127}", tool_id):
                summary["tool_id"] = tool_id
            if event.get("operation") in {"log_parse", "field_mapping", "enum_extract", "threat_mapping", "fill", "remove_mapping", "export", "add_fields", "delete_fields", "merge_fields", "decode_fields", "regex_extract"}:
                summary["operation"] = event["operation"]
            source_kind = {"session.artifacts.enum_values": "enum_values", "session.artifacts.threat_mapping": "threat_mapping",
                           "session.log_classification.entry_rules": "log_classification",
                           "session.log_classification.sub_rules": "log_classification"}.get(event.get("source_ref"))
            if source_kind:
                frozen = json.loads(row["input_snapshot_json"])
                reference = frozen.get("business_inputs", {}).get("refs", {}).get(source_kind)
                if isinstance(reference, dict) and isinstance(reference.get("id"), str):
                    version = db.execute("SELECT version FROM artifacts WHERE id=?", (reference["id"],)).fetchone()
                    if version:
                        summary["input_artifact_id"] = reference["id"]
                        summary["input_artifact_version"] = version[0]
            summary["prompt_version"] = row["prompt_version"]
            summary["standard_field_version"] = row["standard_field_version"]
            summary["provider_config_revision"] = row["provider_config_revision"]
            for key in ("request", "response"):
                if event.get(key) is not None:
                    summary[key] = redact_text(event[key])
            params = event.get("params")
            if isinstance(params, dict):
                summary["params"] = {key: params[key] for key in ("temperature", "top_p", "max_tokens")
                                     if key in params and isinstance(params[key], (int, float)) and not isinstance(params[key], bool)}
            for key in ("request_truncated", "response_truncated"):
                if type(event.get(key)) is bool:
                    summary[key] = event[key]
            db.execute(
                "INSERT INTO model_calls(id,run_id,provider,model,error_code,summary_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (uid(), claim["id"], str(event.get("provider") or "")[:80], str(event.get("model") or "")[:160],
                 error_code, json.dumps(summary, ensure_ascii=False, separators=(",", ":")), now()),
            )
            db.commit()
            return True
