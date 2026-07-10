"""K product knowledge: one-shot image render job queue (P 图片体系阶段 2+3)

One row per image in the product's art-direction brief
(image_instruction_json.images[]). Endpoints enqueue a batch (snapshotting each
image's prompt/placement/SEO fields into the row so a later brief regeneration
cannot shift an in-flight render); the k-worker claims pending rows
(FOR UPDATE SKIP LOCKED), renders each via the I-series gpt-image-2 edit path
with the product's reference photo, and stores the result as a K media asset
whose metadata_json carries placement/position/title/alt/caption/description
for the P upload split (gallery vs description embed).

Revision ID: 20260710_03_k_image_render_jobs
Revises: 20260710_02_rw_product_query_perf
Create Date: 2026-07-10
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260710_03_k_image_render_jobs"
down_revision: str | Sequence[str] | None = "20260710_02_rw_product_query_perf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "k_image_render_jobs"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("placement", sa.String(length=32), nullable=False),
        sa.Column("role_label", sa.String(length=128), nullable=True),
        sa.Column("asset_role", sa.String(length=50), nullable=False),
        sa.Column("mission", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("overlay_text", sa.Text(), nullable=True),
        sa.Column("aspect_ratio", sa.String(length=16), nullable=False),
        sa.Column("seo_json", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("finalized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requested_by_username", sa.String(length=150), nullable=True),
        sa.Column("workspace_key", sa.String(length=128), nullable=True),
        sa.Column("business_context", sa.String(length=64), nullable=True),
        sa.Column("scope_mode", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_k_render_jobs_claim", TABLE, ["status", "created_at"])
    op.create_index("idx_k_render_jobs_product", TABLE, ["product_id"])
    op.create_index("idx_k_render_jobs_batch", TABLE, ["batch_id"])


def downgrade() -> None:
    op.drop_index("idx_k_render_jobs_batch", table_name=TABLE)
    op.drop_index("idx_k_render_jobs_product", table_name=TABLE)
    op.drop_index("idx_k_render_jobs_claim", table_name=TABLE)
    op.drop_table(TABLE)
