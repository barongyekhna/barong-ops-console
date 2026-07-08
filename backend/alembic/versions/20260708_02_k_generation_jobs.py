"""K product knowledge: async generation job queue

Backs the async, parallel copy / image-brief generation. Endpoints enqueue a
row; a worker pool claims pending jobs (FOR UPDATE SKIP LOCKED) and runs the
orchestrator generate methods concurrently. The generated content still lands on
the product (marketing_copy_json / image_instruction_json); this table only
tracks job lifecycle so the UI can poll and the operator can review when done.

Revision ID: 20260708_02_k_generation_jobs
Revises: 20260708_01_k_pk_p_series_fields
Create Date: 2026-07-08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260708_02_k_generation_jobs"
down_revision: str | Sequence[str] | None = "20260708_01_k_pk_p_series_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "k_generation_jobs"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_key", sa.String(length=128), nullable=True),
        sa.Column("business_context", sa.String(length=64), nullable=True),
        sa.Column("scope_mode", sa.String(length=64), nullable=True),
        sa.Column("skill_version", sa.String(length=128), nullable=True),
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
    op.create_index(
        "idx_k_gen_jobs_claim",
        TABLE,
        ["status", "created_at"],
    )
    op.create_index("idx_k_gen_jobs_product", TABLE, ["product_id"])
    op.create_index("idx_k_gen_jobs_batch", TABLE, ["batch_id"])


def downgrade() -> None:
    op.drop_index("idx_k_gen_jobs_batch", table_name=TABLE)
    op.drop_index("idx_k_gen_jobs_product", table_name=TABLE)
    op.drop_index("idx_k_gen_jobs_claim", table_name=TABLE)
    op.drop_table(TABLE)
