"""Bind persistent mapping Drafts to immutable base Artifacts and apply Runs."""
from alembic import op
import sqlalchemy as sa

revision = "0003_mapping_drafts"
down_revision = "0002_durable_runs"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("drafts") as batch:
        batch.add_column(sa.Column("base_artifact_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("apply_run_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("changed_count", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE drafts SET status='discarded' WHERE base_artifact_id IS NULL")
    op.execute("CREATE UNIQUE INDEX drafts_live_base ON drafts(owner_id,base_artifact_id,kind) WHERE status IN ('active','applying')")


def downgrade():
    raise RuntimeError("V2 runtime migration is intentionally irreversible")
