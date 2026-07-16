"""P upload on-demand WooCommerce category mapping cache.

Revision ID: 20260716_01_p_wc_category_map
Revises: 20260715_01_h_site_health
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_01_p_wc_category_map"
down_revision: str | Sequence[str] | None = "20260715_01_h_site_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "k_category_wc_map"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("google_id", sa.String(length=32), nullable=False),
        sa.Column("wc_term_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "wc_term_id > 0",
            name="ck_k_category_wc_map_term_positive",
        ),
        sa.PrimaryKeyConstraint("google_id"),
    )
    op.create_index(
        "ix_k_category_wc_map_wc_term_id",
        TABLE,
        ["wc_term_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_k_category_wc_map_wc_term_id", table_name=TABLE)
    op.drop_table(TABLE)
