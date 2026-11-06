"""Persist per-Run readable business logs for diagnostics."""
from alembic import op

revision = "0008_run_logs"
down_revision = "0007_admin_console"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE runs ADD COLUMN error_message TEXT")
    op.execute("CREATE TABLE IF NOT EXISTS run_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id), created_at TEXT NOT NULL, level TEXT NOT NULL, logger TEXT NOT NULL, step TEXT, message TEXT NOT NULL, exception TEXT)")
    op.execute("CREATE INDEX IF NOT EXISTS run_logs_page ON run_logs(run_id,id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS run_logs")
    op.execute("ALTER TABLE runs DROP COLUMN error_message")
