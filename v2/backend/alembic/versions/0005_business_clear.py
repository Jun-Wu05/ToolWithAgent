"""持久化业务输入清空边界，保留历史文件和产物内容。"""
from alembic import op
import sqlalchemy as sa

revision = "0005_business_clear"
down_revision = "0004_postprocessing"
branch_labels = None
depends_on = None


def upgrade():
    """历史文件默认仍有效，清空只停用业务输入。"""
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    raise RuntimeError("业务清空边界迁移不支持回退")
