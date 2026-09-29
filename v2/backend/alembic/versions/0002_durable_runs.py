"""Confirmation rotation, audit reason and artifact integrity metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0002_durable_runs"
down_revision = "0001_initial_runtime"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("confirmations") as batch:
        batch.add_column(sa.Column("consumed_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("rotated_at", sa.Text(), nullable=True))
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("reason", sa.Text(), nullable=True))
    with op.batch_alter_table("artifacts") as batch:
        batch.add_column(sa.Column("size", sa.Integer(), nullable=True))


def downgrade():
    raise RuntimeError("V2 runtime migration is intentionally irreversible")
