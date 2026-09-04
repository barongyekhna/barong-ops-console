"""「基础档案」面板:建好之后改类型与变体(2026-09-04)。

背景:F→K 搬运绕过建品表单直接落库(单产品 + 一条 default 变体),落库后
档案页没有任何入口能改类型/加变体。PUT /products/{id}/variants 补上这条路。

守住的规矩:
1. 带 variant_id 的行原地更新,variant_sku / variant_hash 不变(媒体按 sku 绑定);
2. 新增行 sku 形如 <SKU>-<8 位大写 hex>,与建品同一套 identity;
3. 还绑着活图的变体拒绝删除(409 VARIANT_HAS_MEDIA),已删除的图只解绑;
4. 多变体 → 单产品收敛成一条 default 行;
5. 裸 PATCH 切类型但变体行对不上 → 409 PRODUCT_TYPE_VARIANTS_MISMATCH;
6. 同步后的产物能过 P 装配的门禁。
"""

from __future__ import annotations

import re
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.unit

from backend.app.db.base import Base
from backend.app.modules.k_series.product_knowledge.errors import (
    KProductTypeVariantsMismatchError,
    KValidationError,
    KVariantHasMediaError,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeVariant,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeCreate,
    ProductKnowledgeUpdate,
    ProductKnowledgeVariantsSync,
    ProductKnowledgeVariantSyncItem,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.service import (
    create_product,
    sync_product_variants,
    update_product,
)
from backend.app.modules.p_series.upload.assemble import _variants, gate_blockers

VARIANT_SKU = re.compile(r"^(?P<parent>.+)-[0-9A-F]{8}$")


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


def _simple_product(db):
    payload = ProductKnowledgeCreate(
        product_name_en="Folding bucket",
        product_type="simple_product",
        raw_input_text="Collapsible bucket for camping.",
        target_market="US",
        regular_price=Decimal("12.00"),
    )
    return create_product(db, payload=payload, scope_context=_scope())


def _variants_of(db, product) -> list[KProductKnowledgeVariant]:
    return list(
        db.scalars(
            select(KProductKnowledgeVariant)
            .where(KProductKnowledgeVariant.product_id == product.id)
            .order_by(KProductKnowledgeVariant.created_at.asc())
        )
    )


def _sync(db, product, product_type, items):
    payload = ProductKnowledgeVariantsSync(product_type=product_type, variants=items)
    return sync_product_variants(
        db, product_id=product.id, payload=payload, scope_context=_scope()
    )


def test_schema_rules_match_create_path() -> None:
    with pytest.raises(ValueError):
        ProductKnowledgeVariantsSync(product_type="variable_product", variants=[])
    with pytest.raises(ValueError):
        ProductKnowledgeVariantsSync(
            product_type="variable_product",
            variants=[ProductKnowledgeVariantSyncItem(color="Blue")],
        )
    with pytest.raises(ValueError):
        ProductKnowledgeVariantsSync(
            product_type="simple_product",
            variants=[
                ProductKnowledgeVariantSyncItem(
                    color="Blue", price_override=Decimal("9.99")
                )
            ],
        )


def test_simple_to_variable_converts_default_row_in_place_and_adds_new_rows() -> None:
    db = _session()
    product = _simple_product(db)
    default = _variants_of(db, product)[0]
    assert default.attributes_json == {"default_variant": True}
    original_sku, original_hash = default.variant_sku, default.variant_hash

    product, touched = _sync(
        db,
        product,
        "variable_product",
        [
            ProductKnowledgeVariantSyncItem(
                variant_id=default.id,
                color="Blue",
                price_override=Decimal("19.99"),
                weight_json={"value": 1.2, "unit": "lb"},
                reference_image_url="https://cbu01.alicdn.com/img/blue.jpg",
            ),
            ProductKnowledgeVariantSyncItem(
                color="Green", price_override=Decimal("19.99")
            ),
        ],
    )

    rows = _variants_of(db, product)
    assert product.product_type == "variable_product"
    assert product.regular_price is None
    assert product.variant_group_key == product.product_key
    assert [row.color for row in rows] == ["Blue", "Green"]
    # 原地转换:身份不变,default 标记去掉,物理规格与参考图进 attributes_json
    assert rows[0].id == default.id
    assert (rows[0].variant_sku, rows[0].variant_hash) == (original_sku, original_hash)
    assert "default_variant" not in rows[0].attributes_json
    assert rows[0].attributes_json["physical"] == {"weight": {"value": 1.2, "unit": "lb"}}
    assert rows[0].attributes_json["reference_image_url"].endswith("blue.jpg")
    assert [variant.id for variant in touched] == [default.id]
    # 新行走同一套 identity
    parent = rows[0].parent_sku
    match = VARIANT_SKU.match(rows[1].variant_sku)
    assert match and match.group("parent") == parent
    assert rows[1].variant_sku != rows[0].variant_sku
    assert rows[1].image_folder == f"images/{product.product_key}/{rows[1].variant_sku}"

    # P 装配读得到、门禁能过
    assembled = _variants(db, product)
    assert sorted(v.color for v in assembled) == ["Blue", "Green"]
    assert not any("变体" in blocker for blocker in gate_blockers(db, product))


def test_editing_keeps_sku_and_preserves_unknown_attribute_keys() -> None:
    db = _session()
    product = _simple_product(db)
    default = _variants_of(db, product)[0]
    default.attributes_json = {"default_variant": True, "legacy_note": "keep me"}
    db.commit()

    product, _ = _sync(
        db,
        product,
        "variable_product",
        [
            ProductKnowledgeVariantSyncItem(
                variant_id=default.id, size="L", price_override=Decimal("5")
            )
        ],
    )
    row = _variants_of(db, product)[0]
    assert row.size == "L" and row.variant_sku == default.variant_sku
    assert row.attributes_json == {"legacy_note": "keep me"}


def test_unknown_variant_id_is_rejected() -> None:
    db = _session()
    product = _simple_product(db)
    with pytest.raises(KValidationError):
        _sync(
            db,
            product,
            "variable_product",
            [
                ProductKnowledgeVariantSyncItem(
                    variant_id=uuid4(), color="Red", price_override=Decimal("1")
                )
            ],
        )


def _media(db, product, variant, status="available"):
    asset = KProductKnowledgeMediaAsset(
        id=uuid4(),
        product_id=product.id,
        variant_id=variant.id,
        variant_sku=variant.variant_sku,
        asset_type="image",
        asset_role="gallery",
        status=status,
        review_status="pending",
        source="manual",
    )
    db.add(asset)
    db.commit()
    return asset


def test_deleting_a_variant_with_live_media_is_refused() -> None:
    db = _session()
    product = _simple_product(db)
    default = _variants_of(db, product)[0]
    product, _ = _sync(
        db,
        product,
        "variable_product",
        [
            ProductKnowledgeVariantSyncItem(
                variant_id=default.id, color="Blue", price_override=Decimal("1")
            ),
            ProductKnowledgeVariantSyncItem(color="Green", price_override=Decimal("1")),
        ],
    )
    blue, green = _variants_of(db, product)
    _media(db, product, green)

    with pytest.raises(KVariantHasMediaError) as excinfo:
        _sync(
            db,
            product,
            "variable_product",
            [
                ProductKnowledgeVariantSyncItem(
                    variant_id=blue.id, color="Blue", price_override=Decimal("1")
                )
            ],
        )
    assert "Green" in str(excinfo.value) and "1 张" in str(excinfo.value)
    db.rollback()
    assert len(_variants_of(db, product)) == 2


def test_deleting_a_variant_with_only_removed_media_detaches_and_deletes() -> None:
    db = _session()
    product = _simple_product(db)
    default = _variants_of(db, product)[0]
    product, _ = _sync(
        db,
        product,
        "variable_product",
        [
            ProductKnowledgeVariantSyncItem(
                variant_id=default.id, color="Blue", price_override=Decimal("1")
            ),
            ProductKnowledgeVariantSyncItem(color="Green", price_override=Decimal("1")),
        ],
    )
    blue, green = _variants_of(db, product)
    asset = _media(db, product, green, status="removed")

    product, _ = _sync(
        db,
        product,
        "variable_product",
        [
            ProductKnowledgeVariantSyncItem(
                variant_id=blue.id, color="Blue", price_override=Decimal("1")
            )
        ],
    )
    assert [row.id for row in _variants_of(db, product)] == [blue.id]
    db.refresh(asset)
    assert asset.variant_id is None and asset.variant_sku == green.variant_sku


def test_variable_to_simple_converges_to_one_default_row() -> None:
    db = _session()
    product = _simple_product(db)
    default = _variants_of(db, product)[0]
    product, _ = _sync(
        db,
        product,
        "variable_product",
        [
            ProductKnowledgeVariantSyncItem(
                variant_id=default.id, color="Blue", price_override=Decimal("1")
            ),
            ProductKnowledgeVariantSyncItem(color="Green", price_override=Decimal("1")),
        ],
    )
    product, _ = _sync(db, product, "simple_product", [])
    rows = _variants_of(db, product)
    assert product.product_type == "simple_product"
    assert product.variant_group_key is None
    assert len(rows) == 1 and rows[0].id == default.id
    assert rows[0].attributes_json == {"default_variant": True}
    assert rows[0].color is None and rows[0].price_override is None


def test_bare_patch_cannot_flip_product_type_against_variant_rows() -> None:
    db = _session()
    product = _simple_product(db)
    with pytest.raises(KProductTypeVariantsMismatchError):
        update_product(
            db,
            product_id=product.id,
            payload=ProductKnowledgeUpdate(product_type="variable_product"),
            scope_context=_scope(),
        )
    db.rollback()
    # 变体行齐了以后,裸 PATCH 同一个值是幂等的,不该被挡
    default = _variants_of(db, product)[0]
    product, _ = _sync(
        db,
        product,
        "variable_product",
        [
            ProductKnowledgeVariantSyncItem(
                variant_id=default.id, color="Blue", price_override=Decimal("1")
            )
        ],
    )
    updated = update_product(
        db,
        product_id=product.id,
        payload=ProductKnowledgeUpdate(
            product_type="variable_product",
            package_weight_json={"value": 2, "unit": "lb"},
        ),
        scope_context=_scope(),
    )
    assert updated.package_weight_json == {"value": 2, "unit": "lb"}
    with pytest.raises(KProductTypeVariantsMismatchError):
        update_product(
            db,
            product_id=product.id,
            payload=ProductKnowledgeUpdate(product_type="simple_product"),
            scope_context=_scope(),
        )
