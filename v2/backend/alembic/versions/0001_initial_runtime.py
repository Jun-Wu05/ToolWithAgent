"""Initial persistent V2 runtime schema."""
from alembic import op
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, archived_at TEXT);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(owner_id,updated_at);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), actor TEXT NOT NULL, kind TEXT NOT NULL, content_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), conversation_id TEXT NOT NULL REFERENCES conversations(id), original_name TEXT NOT NULL, media_type TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, storage_key TEXT NOT NULL, parse_status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), owner_id TEXT NOT NULL REFERENCES users(id), type TEXT NOT NULL, status TEXT NOT NULL, current_run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), attempt INTEGER NOT NULL, status TEXT NOT NULL, input_snapshot_json TEXT NOT NULL, provider_config_revision INTEGER, prompt_version TEXT, standard_field_version TEXT, queued_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, cancel_requested_at TEXT, lease_owner TEXT, lease_expires_at TEXT, leader_epoch INTEGER, fence_token TEXT, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS runs_fifo ON runs(status,queued_at,id);
CREATE TABLE IF NOT EXISTS worker_leases (id TEXT PRIMARY KEY, owner_id TEXT, lease_expires_at TEXT, epoch INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO worker_leases(id,epoch) VALUES ('v2-primary',0);
CREATE TABLE IF NOT EXISTS run_events (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, event_type TEXT NOT NULL, status TEXT NOT NULL, summary_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(run_id,sequence));
CREATE TABLE IF NOT EXISTS conversation_events (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), sequence INTEGER NOT NULL, event_type TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(conversation_id,sequence));
CREATE INDEX IF NOT EXISTS conversation_events_cursor ON conversation_events(conversation_id,sequence);
CREATE TABLE IF NOT EXISTS idempotency_receipts (id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, operation_scope TEXT NOT NULL, key TEXT NOT NULL, request_sha256 TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(principal_id,operation_scope,key));
CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, task_id TEXT NOT NULL, run_id TEXT NOT NULL, kind TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, storage_key TEXT, sha256 TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifact_edges (source_artifact_id TEXT NOT NULL, derived_artifact_id TEXT NOT NULL, relation TEXT NOT NULL, PRIMARY KEY(source_artifact_id,derived_artifact_id));
CREATE TABLE IF NOT EXISTS model_calls (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, provider TEXT, model TEXT, error_code TEXT, summary_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, conversation_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS draft_operations (id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, operation_key TEXT NOT NULL, scope_json TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, validation_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(draft_id,operation_key));
CREATE TABLE IF NOT EXISTS confirmations (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL, checkpoint_revision INTEGER NOT NULL, token_sha256 TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS execution_checkpoints (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, continuation_json TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_configs (id TEXT PRIMARY KEY, provider TEXT NOT NULL, current_revision INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_config_versions (id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, params_json TEXT NOT NULL, secret_version_id TEXT, revision INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_secrets (id TEXT PRIMARY KEY, ciphertext BLOB NOT NULL, nonce BLOB NOT NULL, key_id TEXT NOT NULL, created_at TEXT NOT NULL);
"""

revision = "0001_initial_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for statement in SCHEMA.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError("V2 runtime migration is intentionally irreversible")
