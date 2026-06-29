"""allow file-first I media storage

Revision ID: media_storage_perf_001
Revises: i_image_system_001
Create Date: 2026-06-28

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "media_storage_perf_001"
down_revision: str | Sequence[str] | None = "i_image_system_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASSETS = "i_image_system_assets"


def upgrade() -> None:
    op.alter_column(
        ASSETS,
        "storage_provider",
        existing_type=sa.String(length=100),
        server_default="local_filesystem",
        existing_nullable=False,
    )
    op.alter_column(
        ASSETS,
        "content_bytes",
        existing_type=sa.LargeBinary(),
        nullable=True,
    )
    op.create_index(
        "ix_i_image_assets_scope_status_updated",
        ASSETS,
        ["workspace_key", "business_context", "organization_name", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_i_image_assets_scope_status_updated", table_name=ASSETS)
    op.alter_column(
        ASSETS,
        "storage_provider",
        existing_type=sa.String(length=100),
        server_default="database_blob",
        existing_nullable=False,
    )
    op.execute(f"UPDATE {ASSETS} SET content_bytes = '' WHERE content_bytes IS NULL")
    op.alter_column(
        ASSETS,
        "content_bytes",
        existing_type=sa.LargeBinary(),
        nullable=False,
    )
