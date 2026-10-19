"""业务上传角色，既有文件默认仍为主数据。"""
from alembic import op
import sqlalchemy as sa
revision = "0004_postprocessing"
down_revision = "0003_mapping_drafts"
branch_labels = None
depends_on = None


def upgrade():
    """独立迁移兼容已有 V2 文件，不混入 Chainlit 存储。"""
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("role", sa.Text(), nullable=False, server_default="primary"))


def downgrade():
    raise RuntimeError("V2 runtime migration is intentionally irreversible")
