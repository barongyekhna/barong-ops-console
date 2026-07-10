"""P upload jobs — 上架台账（派单/回报的记录）

控制台点「上架」建一条 job（一单一钥 token）→ 派单给 n8n → n8n 回报结果写回这里。

Revision ID: 20260710_01_p_upload_jobs
Revises: 20260709_04_k_reference_image
Create Date: 2026-07-10
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260710_01_p_upload_jobs"
down_revision: str | Sequence[str] | None = "20260709_04_k_reference_image"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "p_upload_jobs"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="woocommerce"),
        # pending -> dispatched -> success | failed
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("external_product_id", sa.String(length=128), nullable=True),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_p_upload_jobs_job_id"),
    )
    op.create_index("ix_p_upload_jobs_product", T, ["product_id"])
    op.create_index("ix_p_upload_jobs_status", T, ["status"])


def downgrade() -> None:
    op.drop_index("ix_p_upload_jobs_status", table_name=T)
    op.drop_index("ix_p_upload_jobs_product", table_name=T)
    op.drop_table(T)
