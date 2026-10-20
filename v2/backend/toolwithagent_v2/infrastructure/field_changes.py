"""Durable field-change commands around the existing Store transaction boundary."""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from .db import connect
from .store import now, uid


class FieldChanges:
    def __init__(self, store):
        self.store = store

    def _write(self, payload):
        content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        digest = hashlib.sha256(content).hexdigest()
        key = f'field-previews/{digest[:2]}/{digest}'
        final = self.store.root / key
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.store.root / 'staging' / (uid() + '.stage')
        try:
            with temporary.open('wb') as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, final)
        finally:
            temporary.unlink(missing_ok=True)
        return {'storage_key': key, 'sha256': digest}

    def _prepared(self, row):
        reference = json.loads(row['prepared_json'])
        return json.loads(self.store._read_blob(reference, 'field-previews'))

    def _owned(self, db, owner_id, run_id):
        run = self.store._owned_run(db, owner_id, run_id)
        self.store.owns(db, run['conversation_id'], owner_id)
        row = db.execute('SELECT * FROM field_change_previews WHERE run_id=? AND owner_id=?', (run_id, owner_id)).fetchone()
        if row is None:
            raise LookupError('field_preview_not_found')
        return run, row

    def _current(self, db, run):
        return self.store._business_current_db(db, {'conversation_id': run['conversation_id'], 'input': json.loads(run['input_snapshot_json'])})

    def _response(self, db, run, row):
        prepared = self._prepared(row)
        selected = json.loads(row['selected_json'])
        return {'run_id': row['run_id'], 'task_id': run['task_id'], 'revision': row['revision'],
            'status': row['status'], 'current': self._current(db, run), 'selected_group_ids': selected,
            'apply_run_id': row['apply_run_id'], 'applied_artifact_id': row['applied_artifact_id'],
            'undo_run_id': row['undo_run_id'], 'restored_artifact_id': row['restored_artifact_id'],
            'groups': [{key: group[key] for key in ('id', 'fields', 'changes', 'deletes')} | {
                'status': ('applied' if group['id'] in selected else 'not_applied_by_user') if row['status'] in {'applied', 'undone'} else 'selected' if group['id'] in selected else 'not_selected'} for group in prepared['groups']]}

    def get(self, owner_id, run_id):
        with connect(self.store.path) as db:
            run, row = self._owned(db, owner_id, run_id)
            return self._response(db, run, row)

    def prepare(self, worker_id, claim, prepared):
        reference = self._write(prepared)
        with connect(self.store.path) as db:
            db.execute('BEGIN IMMEDIATE')
            run = self.store._valid_claim(db, worker_id, claim)
            if run is None:
                return False
            if not self.store._business_current_db(db, claim):
                self.store._record_state(db, run, 'failed', 'business_input_stale')
                db.commit(); return True
            selected = [group['id'] for group in prepared['groups']]
            db.execute('INSERT INTO field_change_previews(run_id,owner_id,conversation_id,status,prepared_json,selected_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (run['id'], claim['owner_id'], run['conversation_id'], 'ready', json.dumps(reference), json.dumps(selected), now(), now()))
            self.store._assistant_message(db, run['conversation_id'], f"字段变更已准备：{len(selected)} 个变更组，请查看变更。", run['id'])
            self.store._record_state(db, run, 'waiting_confirmation')
            if prepared['direct']:
                original = self.store._owned_run(db, claim['owner_id'], run['id'])
                preview = db.execute('SELECT * FROM field_change_previews WHERE run_id=?', (run['id'],)).fetchone()
                self._apply_db(db, original, preview)
            db.commit(); return True

    def select(self, owner_id, run_id, revision, selected, key):
        with connect(self.store.path) as db:
            db.execute('BEGIN IMMEDIATE')
            run, row = self._owned(db, owner_id, run_id)
            scope = 'field-selection:' + run_id
            digest, receipt = self.store._draft_receipt(db, owner_id, scope, key, [revision, selected])
            if receipt is not None:
                return receipt
            self._editable(db, run, row, revision)
            groups = {group['id'] for group in self._prepared(row)['groups']}
            if len(selected) != len(set(selected)) or not set(selected) <= groups:
                raise ValueError('field_selection_invalid')
            db.execute("UPDATE confirmations SET status='superseded' WHERE run_id=? AND kind='field_delete' AND status='pending'", (run_id,))
            db.execute('UPDATE field_change_previews SET selected_json=?,revision=revision+1,updated_at=? WHERE run_id=?', (json.dumps(selected), now(), run_id))
            row = db.execute('SELECT * FROM field_change_previews WHERE run_id=?', (run_id,)).fetchone()
            result = self._response(db, run, row)
            self.store._save_draft_receipt(db, owner_id, scope, key, digest, result)
            self.store._event(db, row['conversation_id'], 'field_selection_saved', 'run', run_id, {'run_id': run_id, 'revision': row['revision']})
            db.commit(); return result

    def cancel(self, owner_id, run_id, revision, key):
        with connect(self.store.path) as db:
            db.execute('BEGIN IMMEDIATE')
            run, row = self._owned(db, owner_id, run_id)
            scope = 'field-cancel:' + run_id
            digest, receipt = self.store._draft_receipt(db, owner_id, scope, key, revision)
            if receipt is not None:
                return receipt
            if row['revision'] != revision:
                raise ValueError('field_revision_conflict')
            if row['status'] != 'ready':
                raise ValueError('field_preview_not_editable')
            db.execute("UPDATE field_change_previews SET status='cancelled',updated_at=? WHERE run_id=?", (now(), run_id))
            db.execute("UPDATE confirmations SET status='superseded' WHERE run_id=? AND kind='field_delete' AND status='pending'", (run_id,))
            if run['status'] == 'waiting_confirmation':
                self.store._record_state(db, run, 'cancelled')
            result = {'run_id': run_id, 'status': 'cancelled'}
            self.store._save_draft_receipt(db, owner_id, scope, key, digest, result)
            self.store._event(db, row['conversation_id'], 'field_preview_cancelled', 'run', run_id, result)
            db.commit()
            return result

    def _editable(self, db, run, row, revision):
        if row['revision'] != revision:
            raise ValueError('field_revision_conflict')
        if row['status'] != 'ready':
            raise ValueError('field_preview_not_editable')
        if not self._current(db, run):
            raise ValueError('business_input_stale')

    def confirmation(self, owner_id, task_id, revision, key):
        token = secrets.token_urlsafe(32)
        with connect(self.store.path) as db:
            db.execute('BEGIN IMMEDIATE')
            task = db.execute('SELECT current_run_id FROM tasks WHERE id=? AND owner_id=?', (task_id, owner_id)).fetchone()
            if task is None:
                raise LookupError('task_not_found')
            run, row = self._owned(db, owner_id, task['current_run_id'])
            scope = 'field-confirmation:' + task_id
            digest, receipt = self.store._draft_receipt(db, owner_id, scope, key, revision)
            if receipt is not None:
                return receipt
            self._editable(db, run, row, revision)
            selected = json.loads(row['selected_json'])
            deletes = sorted({name for group in self._prepared(row)['groups'] if group['id'] in selected for name in group['deletes']})
            if not deletes:
                raise ValueError('field_delete_confirmation_not_required')
            refs = json.loads(run['input_snapshot_json'])['business_inputs']['refs']
            base = refs.get('field_mapping', {}).get('id')
            affected = []
            if base:
                affected = [dict(item) for item in db.execute("WITH RECURSIVE descendants(id) AS (SELECT derived_artifact_id FROM artifact_edges WHERE source_artifact_id=? UNION SELECT e.derived_artifact_id FROM artifact_edges e JOIN descendants d ON e.source_artifact_id=d.id) SELECT a.id,a.kind,a.version FROM artifacts a JOIN descendants d ON d.id=a.id WHERE a.status='published'", (base,))]
            db.execute("UPDATE confirmations SET status='superseded' WHERE run_id=? AND kind='field_delete' AND status='pending'", (run['id'],))
            checkpoint_id = uid()
            db.execute('INSERT INTO execution_checkpoints(id,run_id,continuation_json,revision,created_at) VALUES(?,?,?,?,?)', (checkpoint_id, run['id'], json.dumps({'field_change_revision': revision}), revision, now()))
            payload = {'deletes': deletes, 'downstream': affected}
            db.execute("INSERT INTO confirmations(id,task_id,run_id,checkpoint_id,checkpoint_revision,token_sha256,kind,payload_json,status,expires_at,created_at) VALUES(?,?,?,?,?,?,'field_delete',?,'pending',?,?)",
                (uid(), task_id, run['id'], checkpoint_id, revision, hashlib.sha256(token.encode()).hexdigest(), json.dumps(payload, ensure_ascii=False), (datetime.now(timezone.utc)+timedelta(hours=24)).isoformat(), now()))
            result = {'token': token, 'run_id': run['id'], 'checkpoint_revision': revision, 'payload': payload}
            self.store._save_draft_receipt(db, owner_id, scope, key, digest, result)
            db.commit()
            return result

    def _apply_db(self, db, run, row):
        snapshot = json.loads(run['input_snapshot_json'])
        snapshot.update({'field_preview_run_id': run['id'], 'field_preview_revision': row['revision'],
            'prepared_reference': json.loads(row['prepared_json']), 'selected_group_ids': json.loads(row['selected_json'])})
        result = self.store._enqueue_task(db, row['owner_id'], row['conversation_id'], 'field_change_apply', snapshot)
        db.execute('UPDATE runs SET provider_config_revision=?,prompt_version=?,standard_field_version=? WHERE id=?',
            (run['provider_config_revision'], run['prompt_version'], run['standard_field_version'], result['run']['id']))
        db.execute("UPDATE field_change_previews SET status='applying',apply_run_id=?,updated_at=? WHERE run_id=?", (result['run']['id'], now(), run['id']))
        if run['status'] == 'waiting_confirmation':
            self.store._record_state(db, run, 'succeeded')
        return result

    def apply(self, owner_id, run_id, revision, key, token=None):
        with connect(self.store.path) as db:
            db.execute('BEGIN IMMEDIATE')
            run, row = self._owned(db, owner_id, run_id)
            scope = 'field-apply:' + run_id
            digest, receipt = self.store._draft_receipt(db, owner_id, scope, key, [revision, token])
            if receipt is not None:
                return receipt
            self._editable(db, run, row, revision)
            selected = json.loads(row['selected_json'])
            if any(group['deletes'] for group in self._prepared(row)['groups'] if group['id'] in selected):
                latest = db.execute('SELECT * FROM execution_checkpoints WHERE run_id=? ORDER BY created_at DESC LIMIT 1', (run_id,)).fetchone()
                approval = db.execute("SELECT * FROM confirmations WHERE run_id=? AND kind='field_delete' AND status='pending' AND token_sha256=?", (run_id, hashlib.sha256((token or '').encode()).hexdigest())).fetchone()
                if not latest or not approval or approval['expires_at'] <= now() or approval['checkpoint_revision'] != revision or approval['checkpoint_id'] != latest['id']:
                    raise ValueError('invalid_confirmation_token')
                db.execute("UPDATE confirmations SET status='consumed',consumed_at=? WHERE id=?", (now(), approval['id']))
            result = self._apply_db(db, run, row)
            self.store._save_draft_receipt(db, owner_id, scope, key, digest, result)
            db.commit(); return result

    def undo(self, owner_id, artifact_id, key):
        with connect(self.store.path) as db:
            db.execute('BEGIN IMMEDIATE')
            artifact = db.execute('SELECT a.*,t.owner_id FROM artifacts a JOIN tasks t ON t.id=a.task_id WHERE a.id=? AND t.owner_id=?', (artifact_id, owner_id)).fetchone()
            if artifact is None:
                raise LookupError('artifact_not_found')
            self.store.owns(db, artifact['conversation_id'], owner_id)
            scope = 'field-undo:' + artifact_id
            digest, receipt = self.store._draft_receipt(db, owner_id, scope, key, artifact_id)
            if receipt is not None:
                return receipt
            row = db.execute("SELECT * FROM field_change_previews WHERE applied_artifact_id=? AND owner_id=? AND status='applied' AND undo_run_id IS NULL", (artifact_id, owner_id)).fetchone()
            if row is None or artifact['status'] != 'published':
                raise ValueError('field_undo_stale')
            self.store._business_command_guard(db, owner_id, artifact['conversation_id'])
            snapshot = self.store._freeze_business(db, artifact['conversation_id'])
            if snapshot['business_inputs']['refs'].get('field_mapping', {}).get('id') != artifact_id:
                raise ValueError('field_undo_stale')
            snapshot.update({'field_preview_run_id': row['run_id'], 'prepared_reference': json.loads(row['prepared_json']), 'undo_artifact_id': artifact_id})
            result = self.store._enqueue_task(db, owner_id, row['conversation_id'], 'field_change_undo', snapshot)
            original = db.execute('SELECT * FROM runs WHERE id=?', (row['apply_run_id'],)).fetchone()
            db.execute('UPDATE runs SET provider_config_revision=?,prompt_version=?,standard_field_version=? WHERE id=?', (original['provider_config_revision'], original['prompt_version'], original['standard_field_version'], result['run']['id']))
            db.execute('UPDATE field_change_previews SET undo_run_id=?,updated_at=? WHERE run_id=?', (result['run']['id'], now(), row['run_id']))
            self.store._save_draft_receipt(db, owner_id, scope, key, digest, result)
            db.commit(); return result

    def read_command(self, claim):
        with connect(self.store.path) as db:
            row = db.execute('SELECT * FROM field_change_previews WHERE run_id=? AND owner_id=?', (claim['input']['field_preview_run_id'], claim['owner_id'])).fetchone()
            if row is None or not self.store._business_current_db(db, claim):
                raise ValueError('business_input_stale')
            if claim['task_type'] == 'field_change_apply':
                valid = row['status'] == 'applying' and row['apply_run_id'] == claim['id'] and row['revision'] == claim['input']['field_preview_revision']
            else:
                valid = row['status'] == 'applied' and row['undo_run_id'] == claim['id'] and row['applied_artifact_id'] == claim['input']['undo_artifact_id']
            if not valid:
                raise ValueError('field_preview_not_editable')
            return self._prepared(row)

    @staticmethod
    def release(db, run_id):
        db.execute("UPDATE field_change_previews SET status='ready',apply_run_id=NULL,revision=revision+1,updated_at=? WHERE status='applying' AND apply_run_id=?", (now(), run_id))
        db.execute('UPDATE field_change_previews SET undo_run_id=NULL,revision=revision+1,updated_at=? WHERE undo_run_id=? AND restored_artifact_id IS NULL', (now(), run_id))
        db.execute("UPDATE field_change_previews SET status='cancelled',updated_at=? WHERE run_id=? AND status='ready'", (now(), run_id))

    def published(self, db, claim, created):
        source = claim['input'].get('field_preview_run_id')
        if not source:
            return
        if claim['task_type'] == 'field_change_apply':
            db.execute("UPDATE field_change_previews SET status='applied',applied_artifact_id=?,updated_at=? WHERE run_id=?", (created['field_mapping'], now(), source))
            prepared = json.loads(self.store._read_blob(claim['input']['prepared_reference'], 'field-previews'))
            if prepared.get('pending_steps'):
                selected = set(claim['input']['selected_group_ids'])
                applied = [group['fields'] for group in prepared['groups'] if group['id'] in selected]
                skipped = [group['fields'] for group in prepared['groups'] if group['id'] not in selected]
                followup = self.store._freeze_business(db, claim['conversation_id'])
                followup.update({'message_id': claim['input'].get('message_id'), 'field_followup': True,
                    'user_text': '字段变更范围已由用户确定，勿重复字段操作。已应用：' + json.dumps(applied, ensure_ascii=False)
                        + '；用户未应用：' + json.dumps(skipped, ensure_ascii=False)
                        + '。请依据当前会话重新规划剩余业务要求：' + json.dumps(prepared['pending_steps'], ensure_ascii=False)})
                self.store._enqueue_task(db, claim['owner_id'], claim['conversation_id'], 'user_request', followup)
        elif claim['task_type'] == 'field_change_undo':
            db.execute("UPDATE field_change_previews SET status='undone',restored_artifact_id=?,updated_at=? WHERE run_id=?", (created['field_mapping'], now(), source))
