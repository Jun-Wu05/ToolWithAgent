"""Durable field change preparation, selection and immutable version links."""
from alembic import op

revision = '0006_field_changes'
down_revision = '0005_business_clear'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE field_change_previews (
        run_id TEXT PRIMARY KEY REFERENCES runs(id), owner_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL REFERENCES conversations(id), revision INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL, prepared_json TEXT NOT NULL, selected_json TEXT NOT NULL,
        apply_run_id TEXT, applied_artifact_id TEXT, undo_run_id TEXT, restored_artifact_id TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')


def downgrade():
    raise RuntimeError('V2 runtime migration is intentionally irreversible')
