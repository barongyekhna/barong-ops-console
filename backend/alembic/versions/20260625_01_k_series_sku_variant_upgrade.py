"""upgrade K product knowledge to SKU and variant products

Revision ID: k_sku_variant_001
Revises: ai_provider_layer_001
Create Date: 2026-06-25

"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "k_sku_variant_001"
down_revision: str | Sequence[str] | None = "ai_provider_layer_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRODUCTS = "k_product_knowledge_products"
VARIANTS = "k_product_knowledge_variants"
MEDIA_ASSETS = "k_product_knowledge_media_assets"


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def user_trace_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Uuid(), nullable=True)


def _default_variant_hash(product_key: str) -> str:
    seed = {"default_variant": True, "product_key": product_key}
    canonical = json.dumps(seed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8].upper()


def upgrade() -> None:
    op.add_column(PRODUCTS, sa.Column("parent_sku", sa.String(length=128), nullable=True))
    op.add_column(PRODUCTS, sa.Column("target_market", sa.String(length=50), nullable=True))

    op.create_unique_constraint(
        "uq_kpk_products_product_key_global",
        PRODUCTS,
        ["product_key"],
    )
    op.create_check_constraint(
        "ck_kpk_products_valid_product_type",
        PRODUCTS,
        "product_type IS NULL OR product_type IN ('simple_product', 'variable_product')",
    )
    op.create_index(
        "ix_kpk_products_scope_parent_sku",
        PRODUCTS,
        ["workspace_key", "business_context", "parent_sku"],
    )
    op.create_index("ix_kpk_products_target_market", PRODUCTS, ["target_market"])

    op.create_table(
        VARIANTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("parent_sku", sa.String(length=128), nullable=False),
        sa.Column("variant_sku", sa.String(length=180), nullable=False),
        sa.Column("variant_hash", sa.String(length=40), nullable=False),
        sa.Column("color", sa.String(length=128), nullable=True),
        sa.Column("size", sa.String(length=128), nullable=True),
        sa.Column("function", sa.String(length=128), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("price_override", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("attributes_json", json_type(), nullable=True),
        sa.Column("image_folder", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_variants_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_variants")),
        sa.UniqueConstraint("variant_sku", name="uq_kpk_variants_variant_sku_global"),
        sa.UniqueConstraint("product_id", "variant_hash", name="uq_kpk_variants_product_hash"),
    )
    op.create_index("ix_kpk_variants_product", VARIANTS, ["product_id"])
    op.create_index("ix_kpk_variants_parent_sku", VARIANTS, ["parent_sku"])
    op.create_index("ix_kpk_variants_variant_sku", VARIANTS, ["variant_sku"])
    op.create_index("ix_kpk_variants_status", VARIANTS, ["status"])
    op.create_index("ix_kpk_variants_created", VARIANTS, ["created_at"])

    op.add_column(MEDIA_ASSETS, sa.Column("variant_id", sa.Uuid(), nullable=True))
    op.add_column(MEDIA_ASSETS, sa.Column("variant_sku", sa.String(length=180), nullable=True))
    op.create_foreign_key(
        "fk_kpk_media_assets_variant_id_variants",
        MEDIA_ASSETS,
        VARIANTS,
        ["variant_id"],
        ["id"],
    )
    op.create_index(
        "ix_kpk_media_assets_variant_sku",
        MEDIA_ASSETS,
        ["product_id", "variant_sku"],
    )

    connection = op.get_bind()
    products = connection.execute(
        sa.text(
            "select id, product_key, sku, parent_sku, product_type, target_market "
            f"from {PRODUCTS}"
        )
    ).mappings()
    for product in products:
        product_key = str(product["product_key"])
        parent_sku = product["parent_sku"] or product["sku"] or product_key
        product_type = product["product_type"] or "simple_product"
        target_market = product["target_market"] or "US"
        variant_hash = _default_variant_hash(product_key)
        variant_sku = f"{parent_sku}-{variant_hash}"
        image_folder = f"images/{product_key}/{variant_sku}"
        variant_id = uuid4()
        connection.execute(
            sa.text(
                f"update {PRODUCTS} "
                "set parent_sku = :parent_sku, sku = coalesce(sku, :parent_sku), "
                "product_type = :product_type, target_market = :target_market "
                "where id = :product_id"
            ),
            {
                "parent_sku": parent_sku,
                "product_id": product["id"],
                "product_type": product_type,
                "target_market": target_market,
            },
        )
        connection.execute(
            sa.text(
                f"insert into {VARIANTS} "
                "(id, product_id, parent_sku, variant_sku, variant_hash, "
                "attributes_json, image_folder, status) "
                "values (:id, :product_id, :parent_sku, :variant_sku, "
                ":variant_hash, :attributes_json, :image_folder, 'active')"
            ),
            {
                "attributes_json": json.dumps({"default_variant": True}),
                "id": variant_id,
                "image_folder": image_folder,
                "parent_sku": parent_sku,
                "product_id": product["id"],
                "variant_hash": variant_hash,
                "variant_sku": variant_sku,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_kpk_media_assets_variant_sku", table_name=MEDIA_ASSETS)
    op.drop_constraint(
        "fk_kpk_media_assets_variant_id_variants",
        MEDIA_ASSETS,
        type_="foreignkey",
    )
    op.drop_column(MEDIA_ASSETS, "variant_sku")
    op.drop_column(MEDIA_ASSETS, "variant_id")

    op.drop_index("ix_kpk_variants_created", table_name=VARIANTS)
    op.drop_index("ix_kpk_variants_status", table_name=VARIANTS)
    op.drop_index("ix_kpk_variants_variant_sku", table_name=VARIANTS)
    op.drop_index("ix_kpk_variants_parent_sku", table_name=VARIANTS)
    op.drop_index("ix_kpk_variants_product", table_name=VARIANTS)
    op.drop_table(VARIANTS)

    op.drop_index("ix_kpk_products_target_market", table_name=PRODUCTS)
    op.drop_index("ix_kpk_products_scope_parent_sku", table_name=PRODUCTS)
    op.drop_constraint("ck_kpk_products_valid_product_type", PRODUCTS, type_="check")
    op.drop_constraint("uq_kpk_products_product_key_global", PRODUCTS, type_="unique")
    op.drop_column(PRODUCTS, "target_market")
    op.drop_column(PRODUCTS, "parent_sku")
