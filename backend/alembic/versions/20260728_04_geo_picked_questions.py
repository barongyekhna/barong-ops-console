"""GEO topic sourcing: operator-picked buyer questions on a cluster.

Adds geo_content_clusters.picked_questions_json — the server-owned required set
of real buyer questions the content engine must answer (milestone 2). Additive.

Revision ID: 20260728_04_geo_picked_questions
Revises: 20260728_03_b2b_store_types
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_04_geo_picked_questions"
down_revision: str | Sequence[str] | None = "20260728_03_b2b_store_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "geo_content_clusters",
        sa.Column("picked_questions_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_content_clusters", "picked_questions_json")
