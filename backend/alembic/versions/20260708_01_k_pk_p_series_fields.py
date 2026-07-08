"""K product knowledge: P-series channel + skill-generated copy/image-brief fields

Adds the channel partition (amazon|dtc) and persisted marketing copy + image
art-direction instruction (each with its skill version) to
k_product_knowledge_products. All columns are nullable or defaulted, so existing
rows are unaffected.

Revision ID: 20260708_01_k_pk_p_series_fields
Revises: 20260705_01_ra_framework_schema
Create Date: 2026-07-08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260708_01_k_pk_p_series_fields"
down_revision: str | Sequence[str] | None = "20260705_01_ra_framework_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRODUCTS = "k_product_knowledge_products"
CHANNEL_INDEX = "idx_k_pk_products_channel"


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        PRODUCTS,
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default="dtc",
        ),
    )
    op.add_column(
        PRODUCTS,
        sa.Column("marketing_copy_json", json_type(), nullable=True),
    )
    op.add_column(
        PRODUCTS,
        sa.Column("marketing_copy_skill_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        PRODUCTS,
        sa.Column("image_instruction_json", json_type(), nullable=True),
    )
    op.add_column(
        PRODUCTS,
        sa.Column(
            "image_instruction_skill_version",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.create_index(CHANNEL_INDEX, PRODUCTS, ["channel"])


def downgrade() -> None:
    op.drop_index(CHANNEL_INDEX, table_name=PRODUCTS)
    op.drop_column(PRODUCTS, "image_instruction_skill_version")
    op.drop_column(PRODUCTS, "image_instruction_json")
    op.drop_column(PRODUCTS, "marketing_copy_skill_version")
    op.drop_column(PRODUCTS, "marketing_copy_json")
    op.drop_column(PRODUCTS, "channel")
