from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeVariant,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeCreate,
    ProductKnowledgeVariantItem,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.service import create_product


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


def test_create_rejects_manual_product_key() -> None:
    with pytest.raises(ValueError, match="product_key is auto-generated"):
        ProductKnowledgeCreate(
            product_key="manual-key",
            parent_sku="PARENT-001",
            product_name_en="Pump",
            raw_input_text="Pump description",
            target_market="US",
        )


def test_variable_product_creates_parent_sku_and_variant_skus() -> None:
    db = _session()
    payload = ProductKnowledgeCreate(
        parent_sku="pump family",
        product_name_en="Pump family",
        product_type="variable_product",
        raw_input_text="Pump family description",
        target_market="US",
        variants=[
            ProductKnowledgeVariantItem(
                color="blue",
                size="M",
                function="standard",
                quantity=10,
                attributes={"material": "steel"},
            ),
            ProductKnowledgeVariantItem(
                color="red",
                size="L",
                function="heavy",
                quantity=5,
                attributes={"material": "alloy"},
            ),
        ],
    )

    product = create_product(db, payload=payload, scope_context=_scope())
    variants = list(
        db.scalars(
            select(KProductKnowledgeVariant)
            .where(KProductKnowledgeVariant.product_id == product.id)
            .order_by(KProductKnowledgeVariant.variant_sku.asc())
        )
    )

    assert product.product_key.startswith("kprod_")
    assert product.product_type == "variable_product"
    assert product.parent_sku == "PUMP-FAMILY"
    assert len(variants) == 2
    assert all(item.variant_sku.startswith("PUMP-FAMILY-") for item in variants)
    assert all(item.image_folder.startswith(f"images/{product.product_key}/") for item in variants)
