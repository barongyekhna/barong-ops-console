"""GEO clusters cover many products; add the product-spotlight item type.

One cluster per category: every product in that category shares the topic, so a
cluster tracks a product list instead of a single seed. Products attached since
the last generation are tracked separately so approved content is never silently
invalidated — the operator sees a "new products" hint and decides to refresh.

``product_spotlight`` is the opt-in article for a differentiated product inside a
shared cluster (panda-shaped shower vs the plain one) — distinct selling points
without splitting the topic into duplicate clusters.

Revision ID: 20260728_05_geo_cluster_products
Revises: 20260728_04_geo_picked_questions
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_05_geo_cluster_products"
down_revision: str | Sequence[str] | None = "20260728_04_geo_picked_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ITEM_TYPES = "item_type IN ('hub', 'how_it_works', 'comparison', 'scenario', 'qa')"
_NEW_ITEM_TYPES = (
    "item_type IN ("
    "'hub', 'how_it_works', 'comparison', 'scenario', 'qa', 'product_spotlight'"
    ")"
)


def upgrade() -> None:
    op.add_column(
        "geo_content_clusters",
        sa.Column("product_ids_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "geo_content_clusters",
        sa.Column("pending_product_ids_json", sa.JSON(), nullable=True),
    )
    # Backfill: existing clusters already cover their seed product.
    op.execute(
        "UPDATE geo_content_clusters "
        "SET product_ids_json = json_build_array(seed_product_id::text) "
        "WHERE seed_product_id IS NOT NULL AND product_ids_json IS NULL"
    )
    op.drop_constraint(
        "ck_geo_items_valid_type", "geo_content_items", type_="check"
    )
    op.create_check_constraint(
        "ck_geo_items_valid_type", "geo_content_items", _NEW_ITEM_TYPES
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM geo_content_items WHERE item_type = 'product_spotlight'"
    )
    op.drop_constraint(
        "ck_geo_items_valid_type", "geo_content_items", type_="check"
    )
    op.create_check_constraint(
        "ck_geo_items_valid_type", "geo_content_items", _OLD_ITEM_TYPES
    )
    op.drop_column("geo_content_clusters", "pending_product_ids_json")
    op.drop_column("geo_content_clusters", "product_ids_json")
