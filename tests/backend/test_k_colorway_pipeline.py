"""颜色变体图片管线(2026-07-23):按色参考图 → 每色主图 → 变体挂图。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.modules.k_series.product_knowledge.image_render_jobs import (
    _colorway_specs,
    _spec_seo,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeVariant,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeCreate,
    ProductKnowledgeVariantItem,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.service import create_product

pytestmark = pytest.mark.unit


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _scope() -> KScopeContext:
    return KScopeContext(
        workspace_key="org_test",
        business_context="independent_store",
        scope_mode="production",
    )


def test_variant_reference_url_lands_in_attributes_json() -> None:
    db = _session()
    payload = ProductKnowledgeCreate(
        product_name_en="Color Ball",
        product_type="variable_product",
        raw_input_text="colorful stress ball",
        target_market="US",
        variants=[
            ProductKnowledgeVariantItem(
                color="Red", quantity=1, price_override=Decimal("9.99"),
                reference_image_url="https://cbu01.alicdn.com/img/red.jpg",
            ),
            ProductKnowledgeVariantItem(
                color="Red", quantity=2, price_override=Decimal("17.99"),
            ),
            ProductKnowledgeVariantItem(
                color="Blue", quantity=1, price_override=Decimal("9.99"),
                reference_image_url="https://cbu01.alicdn.com/img/blue.jpg",
            ),
        ],
    )
    product = create_product(db, payload=payload, scope_context=_scope())
    rows = list(db.scalars(select(KProductKnowledgeVariant).where(
        KProductKnowledgeVariant.product_id == product.id)))
    by_color_qty = {(r.color, r.quantity): r.attributes_json or {} for r in rows}
    assert by_color_qty[("Red", 1)]["reference_image_url"].endswith("red.jpg")
    assert "reference_image_url" not in by_color_qty[("Red", 2)]
    assert by_color_qty[("Blue", 1)]["reference_image_url"].endswith("blue.jpg")

    with pytest.raises(ValueError, match="http"):
        ProductKnowledgeVariantItem(
            color="Red", price_override=Decimal("1"),
            reference_image_url="ftp://bad/x.jpg",
        )


def test_colorway_specs_generated_per_color_with_stable_positions() -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from backend.app.modules.k_series.product_knowledge.models import (
        KProductKnowledgeMediaAsset,
    )

    db = _session()
    payload = ProductKnowledgeCreate(
        product_name_en="Color Ball",
        product_type="variable_product",
        raw_input_text="colorful stress ball",
        target_market="US",
        variants=[
            ProductKnowledgeVariantItem(
                color="Red", quantity=1, price_override=Decimal("9.99")),
        ],
    )
    product = create_product(db, payload=payload, scope_context=_scope())
    variant = db.scalars(select(KProductKnowledgeVariant).where(
        KProductKnowledgeVariant.product_id == product.id)).first()
    for color in ("Red", "Blue"):
        db.add(KProductKnowledgeMediaAsset(
            id=uuid4(), product_id=product.id,
            variant_id=variant.id, variant_sku=variant.variant_sku,
            asset_type="image", asset_role="reference", status="available",
            review_status="not_applicable", storage_provider="local_filesystem",
            object_key=f"images/x/{color}.jpg", file_size=10, mime_type="image/jpeg",
            source="f_supplier_reference",
            metadata_json={"variant_reference": True, "variant_color": color},
            image_folder="x",
        ) if hasattr(KProductKnowledgeMediaAsset, "image_folder") else KProductKnowledgeMediaAsset(
            id=uuid4(), product_id=product.id,
            variant_id=variant.id, variant_sku=variant.variant_sku,
            asset_type="image", asset_role="reference", status="available",
            review_status="not_applicable", storage_provider="local_filesystem",
            object_key=f"images/x/{color}.jpg", file_size=10, mime_type="image/jpeg",
            source="f_supplier_reference",
            metadata_json={"variant_reference": True, "variant_color": color},
        ))
    db.flush()

    specs = _colorway_specs(db, product, known_positions={1, 2, 3})
    assert [s["variant_color"] for s in specs] == ["Blue", "Red"]
    assert all(s["position"] > 100 for s in specs)
    assert all(s["placement"] == "gallery" for s in specs)
    assert all(s["reference_asset_id"] for s in specs)
    for s in specs:
        seo = _spec_seo(s)
        assert seo["variant_color"] == s["variant_color"]
        for field in ("title", "alt", "caption", "description"):
            assert seo[field]
