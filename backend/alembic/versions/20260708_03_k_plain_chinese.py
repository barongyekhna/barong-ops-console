"""K product knowledge: plain-Chinese (人话) versions of copy + image brief

The generated copy / image-brief JSON is hard to read. After producing the
authoritative English original, a DeepSeek pass turns it into plain Chinese for
operator review. Stored separately; the original is the ONLY thing sent to
P-series / into I-series -- the Chinese is display-only.

Revision ID: 20260708_03_k_plain_chinese
Revises: 20260708_02_k_generation_jobs
Create Date: 2026-07-08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260708_03_k_plain_chinese"
down_revision: str | Sequence[str] | None = "20260708_02_k_generation_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRODUCTS = "k_product_knowledge_products"


def upgrade() -> None:
    op.add_column(PRODUCTS, sa.Column("marketing_copy_zh", sa.Text(), nullable=True))
    op.add_column(PRODUCTS, sa.Column("image_instruction_zh", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(PRODUCTS, "image_instruction_zh")
    op.drop_column(PRODUCTS, "marketing_copy_zh")
