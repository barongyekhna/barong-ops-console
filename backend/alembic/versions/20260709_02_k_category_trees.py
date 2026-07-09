"""K category trees: full Amazon (Keepa) + Google taxonomies + alignment

Two complete category trees replicated into K, plus an alignment map between
them. Amazon-group products drop into their Amazon (Keepa) node directly (R-W
already tags every product with it); DTC/独立站 products drop into the aligned
Google category. Manual K uploads pick from the dropdown.

Revision ID: 20260709_02_k_category_trees
Revises: 20260709_01_p_notifications
Create Date: 2026-07-09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260709_02_k_category_trees"
down_revision: str | Sequence[str] | None = "20260709_01_p_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tree_table(name: str, id_len: int) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(length=id_len), primary_key=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("full_path", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.String(length=id_len), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_leaf", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(f"ix_{name}_parent", name, ["parent_id"])
    op.create_index(f"ix_{name}_leaf", name, ["is_leaf"])


def upgrade() -> None:
    # Google Product Taxonomy — the 独立站 / GMC tree.
    _tree_table("k_category_google", 32)

    # Amazon browse-node tree as Keepa reports it (marketplace-scoped).
    op.create_table(
        "k_category_amazon",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("full_path", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.String(length=32), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_leaf", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "marketplace", sa.String(length=8), nullable=False, server_default="US"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_k_category_amazon_parent", "k_category_amazon", ["parent_id"])
    op.create_index("ix_k_category_amazon_leaf", "k_category_amazon", ["is_leaf"])

    # Alignment: one chosen Google category per Amazon node (+ provenance).
    op.create_table(
        "k_category_alignment",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("amazon_id", sa.String(length=32), nullable=False),
        sa.Column("marketplace", sa.String(length=8), nullable=False, server_default="US"),
        sa.Column("google_id", sa.String(length=32), nullable=True),
        # exact | normalized | ai | manual
        sa.Column("method", sa.String(length=16), nullable=False, server_default="ai"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("amazon_id", "marketplace", name="uq_k_cat_align_amazon"),
    )
    op.create_index("ix_k_category_alignment_google", "k_category_alignment", ["google_id"])


def downgrade() -> None:
    op.drop_table("k_category_alignment")
    op.drop_index("ix_k_category_amazon_leaf", table_name="k_category_amazon")
    op.drop_index("ix_k_category_amazon_parent", table_name="k_category_amazon")
    op.drop_table("k_category_amazon")
    op.drop_index("ix_k_category_google_leaf", table_name="k_category_google")
    op.drop_index("ix_k_category_google_parent", table_name="k_category_google")
    op.drop_table("k_category_google")
