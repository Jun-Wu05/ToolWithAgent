"""Admin console: sanitized before/after audit detail and lookup indexes."""
from alembic import op
import sqlalchemy as sa

revision = "0007_admin_console"
down_revision = "0006_field_changes"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("before_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("after_json", sa.Text(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS audit_events_created ON audit_events(created_at DESC, id DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS runs_admin_listing ON runs(status, updated_at DESC, id DESC)")


def downgrade():
    raise RuntimeError("V2 runtime migration is intentionally irreversible")
