"""Close the review loop: what a critique-driven rewrite actually fixed.

The DeepSeek reading aid criticises each piece; some critiques are fixable by
rewording, others cannot be honoured without inventing facts we do not have
(e.g. "state the recommended charging wattage" when no such spec exists). This
records both — what the rewrite addressed, and what it refused to fake and why —
so unfixable critiques surface as data gaps to fill in K instead of silently
becoming fabricated claims.

Revision ID: 20260728_07_geo_item_revision
Revises: 20260728_06_geo_item_analysis
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_07_geo_item_revision"
down_revision: str | Sequence[str] | None = "20260728_06_geo_item_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "geo_content_items",
        sa.Column("revision_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_content_items", "revision_json")
