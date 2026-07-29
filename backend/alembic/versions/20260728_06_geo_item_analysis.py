"""Per-item review aid: the DeepSeek-flash reading of each GEO content piece.

Reviewing English AI-written guide content is hard when you don't read it
natively, so every generated piece carries its own analysis — Chinese
translation, what it actually does for GEO, and why it is written that way.

Revision ID: 20260728_06_geo_item_analysis
Revises: 20260728_05_geo_cluster_products
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_06_geo_item_analysis"
down_revision: str | Sequence[str] | None = "20260728_05_geo_cluster_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "geo_content_items",
        sa.Column("analysis_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_content_items", "analysis_json")
