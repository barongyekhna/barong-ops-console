"""R-W product query performance indexes

Revision ID: 20260710_02_rw_product_query_perf
Revises: 20260710_01_p_upload_jobs
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260710_02_rw_product_query_perf"
down_revision: str | Sequence[str] | None = "20260710_01_p_upload_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_products_rw_updated_at_desc_nulls_last "
            "ON products_rw (updated_at DESC NULLS LAST, asin)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_products_rw_skill_score_desc_nulls_last "
            "ON products_rw (skill_score DESC NULLS LAST, asin)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_products_rw_title_trgm "
            "ON products_rw USING gin (lower(title) gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_products_rw_title_zh_trgm "
            "ON products_rw USING gin (lower(COALESCE(title_zh, '')) gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_products_rw_asin_trgm "
            "ON products_rw USING gin (lower(asin) gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_products_rw_category_trgm "
            "ON products_rw USING gin (lower(category) gin_trgm_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_products_rw_category_trgm"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_products_rw_asin_trgm")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_products_rw_title_zh_trgm"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_products_rw_title_trgm")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_products_rw_skill_score_desc_nulls_last"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_products_rw_updated_at_desc_nulls_last"
        )
