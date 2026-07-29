"""GEO rail 2: dispatch queue for refreshing product-page backlinks.

Guides already link to the product (rail 1). This queue drives the return leg: a
dedicated n8n workflow rewrites only the marker-delimited "Learn more" block in a
live Woo product description, so a product page can lead a buyer — or an answer
engine — back into the guides that cover it.

Deliberately not part of the P upload path: re-running a full upload to change a
link block would re-upload every image and rewrite price/category/schema.

Revision ID: 20260729_03_geo_backlink
Revises: 20260729_02_b2b_prospect_screening
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_03_geo_backlink"
down_revision: str | Sequence[str] | None = "20260729_02_b2b_prospect_screening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WS_DEFAULT = "default_independent_store"
_BC_DEFAULT = "independent_store"
_SM_DEFAULT = "adapter_pending"


def upgrade() -> None:
    op.create_table(
        "geo_backlink_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "workspace_key",
            sa.String(length=128),
            nullable=False,
            server_default=_WS_DEFAULT,
        ),
        sa.Column(
            "business_context",
            sa.String(length=64),
            nullable=False,
            server_default=_BC_DEFAULT,
        ),
        sa.Column(
            "scope_mode",
            sa.String(length=32),
            nullable=False,
            server_default=_SM_DEFAULT,
        ),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=32),
            nullable=False,
            server_default="woocommerce",
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="queued"
        ),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("targets_json", sa.JSON(), nullable=True),
        sa.Column("updated_items_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_username", sa.String(length=255), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name="ck_geo_backlink_jobs_valid_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_geo_backlink_jobs"),
        sa.UniqueConstraint("job_id", name="uq_geo_backlink_jobs_job_id"),
    )
    op.create_index(
        "ix_geo_backlink_jobs_status", "geo_backlink_jobs", ["status"], unique=False
    )
    op.create_index(
        "ix_geo_backlink_jobs_created",
        "geo_backlink_jobs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_geo_backlink_jobs_created", table_name="geo_backlink_jobs")
    op.drop_index("ix_geo_backlink_jobs_status", table_name="geo_backlink_jobs")
    op.drop_table("geo_backlink_jobs")
