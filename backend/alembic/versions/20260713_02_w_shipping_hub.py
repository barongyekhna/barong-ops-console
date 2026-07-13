"""W-A 运费中枢 — 运费模板、确定性规则与 K 产品运费治理字段

Revision ID: 20260713_02_w_shipping_hub
Revises: 20260713_01_f_sourcing_mode
Create Date: 2026-07-13
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260713_02_w_shipping_hub"
down_revision: str | Sequence[str] | None = "20260713_01_f_sourcing_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLASSES = "w_shipping_classes"
RULES = "w_shipping_rules"
PRODUCTS = "k_product_knowledge_products"


def upgrade() -> None:
    op.create_table(
        CLASSES,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "origin",
            sa.String(length=20),
            nullable=False,
            server_default="cn_direct",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="100"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "origin IN ('cn_direct', 'us_stock')",
            name="ck_w_shipping_classes_valid_origin",
        ),
        sa.UniqueConstraint("slug", name="uq_w_shipping_classes_slug"),
    )

    op.create_table(
        RULES,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(length=30), nullable=False),
        sa.Column("min_weight_kg", sa.Numeric(8, 3), nullable=True),
        sa.Column("max_weight_kg", sa.Numeric(8, 3), nullable=True),
        sa.Column(
            "shipping_class_slug", sa.String(length=128), nullable=False
        ),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "rule_type IN ('us_stock_override', 'battery_override', 'weight_band')",
            name="ck_w_shipping_rules_valid_type",
        ),
    )
    op.create_index(
        "ix_w_rules_priority", RULES, ["active", "priority"]
    )

    op.add_column(
        PRODUCTS,
        sa.Column(
            "contains_battery",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        PRODUCTS,
        sa.Column(
            "us_stock",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        PRODUCTS,
        sa.Column("shipping_assignment_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        PRODUCTS,
        sa.Column(
            "shipping_review_needed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column(PRODUCTS, "shipping_review_needed")
    op.drop_column(PRODUCTS, "shipping_assignment_json")
    op.drop_column(PRODUCTS, "us_stock")
    op.drop_column(PRODUCTS, "contains_battery")

    op.drop_index("ix_w_rules_priority", table_name=RULES)
    op.drop_table(RULES)
    op.drop_table(CLASSES)
