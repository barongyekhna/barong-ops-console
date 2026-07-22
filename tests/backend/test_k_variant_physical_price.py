"""多变体产品新规(2026-07-22 用户拍板)的回归测试。

1. 多变体产品父体价一律置空,价格逐变体必填;
2. 变体级尺寸/重量落进 attributes_json.physical,P 装配按变体读取;
3. P 门禁:多变体看变体价齐不齐,单产品看父体价;
4. 建品支持多条参考图链接(去重 + http 校验)。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# 内存 SQLite 自建 schema,不碰生产库道 —— 明确归 unit 道
pytestmark = pytest.mark.unit

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
from backend.app.modules.p_series.upload.assemble import (
    _variant_physical,
    _variants,
    gate_blockers,
)


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


def _variable_payload(**overrides) -> ProductKnowledgeCreate:
    defaults = {
        "product_name_en": "Squeeze ball family",
        "product_type": "variable_product",
        "raw_input_text": "Stress ball, 1-pack and 2-pack.",
        "target_market": "US",
        "regular_price": Decimal("99.00"),
        "variants": [
            ProductKnowledgeVariantItem(
                function="1-pack",
                price_override=Decimal("14.99"),
                dimensions_json={"length": 2.5, "width": 2.5, "height": 2.5, "unit": "inch"},
                weight_json={"value": 0.2, "unit": "lb"},
            ),
            ProductKnowledgeVariantItem(
                function="2-pack",
                price_override=Decimal("24.99"),
                dimensions_json={"length": 5.0, "width": 2.5, "height": 2.5, "unit": "inch"},
                weight_json={"value": 0.4, "unit": "lb"},
            ),
        ],
    }
    defaults.update(overrides)
    return ProductKnowledgeCreate(**defaults)


def test_variable_product_clears_parent_price_and_requires_variant_prices() -> None:
    payload = _variable_payload()
    assert payload.regular_price is None

    with pytest.raises(ValueError, match="每个变体都必须填写价格"):
        _variable_payload(
            variants=[
                ProductKnowledgeVariantItem(function="1-pack"),
            ]
        )


def test_variant_physical_specs_persist_into_attributes_json() -> None:
    db = _session()
    product = create_product(db, payload=_variable_payload(), scope_context=_scope())

    rows = list(
        db.scalars(
            select(KProductKnowledgeVariant)
            .where(KProductKnowledgeVariant.product_id == product.id)
            .order_by(KProductKnowledgeVariant.created_at.asc())
        )
    )
    assert len(rows) == 2
    # sorted() 只为稳定断言顺序;两行都必须带 physical
    physicals = sorted(
        ((row.attributes_json or {}).get("physical", {}) for row in rows),
        key=lambda item: item["weight"]["value"],
    )
    assert physicals[0]["dimensions"]["length"] == 2.5
    assert physicals[0]["weight"] == {"value": 0.2, "unit": "lb"}
    assert physicals[1]["dimensions"]["length"] == 5.0

    # P 装配按变体读出物理规格与价格
    variants = _variants(db, product)
    assert {v.weight["value"] for v in variants if v.weight} == {0.2, 0.4}
    assert {str(v.price.regular) for v in variants if v.price} == {"14.99", "24.99"}


def test_gate_uses_variant_prices_for_variable_products() -> None:
    db = _session()
    product = create_product(db, payload=_variable_payload(), scope_context=_scope())

    blockers = gate_blockers(db, product)
    assert not any("价格" in item for item in blockers)

    # 抽掉一个变体价 → 门禁必须拦
    variant = db.scalars(
        select(KProductKnowledgeVariant).where(
            KProductKnowledgeVariant.product_id == product.id
        )
    ).first()
    variant.price_override = None
    db.add(variant)
    db.commit()
    blockers = gate_blockers(db, product)
    assert any("变体价格缺失" in item for item in blockers)


def test_simple_product_price_gate_unchanged() -> None:
    db = _session()
    payload = ProductKnowledgeCreate(
        product_name_en="Simple pump",
        raw_input_text="Simple pump description",
        target_market="US",
    )
    product = create_product(db, payload=payload, scope_context=_scope())
    assert any("价格缺失" in item for item in gate_blockers(db, product))


def test_reference_image_urls_validation() -> None:
    payload = ProductKnowledgeCreate(
        product_name_en="Pump",
        raw_input_text="Pump description",
        target_market="US",
        reference_image_urls=[
            " https://cbu01.alicdn.com/img/a.jpg ",
            "https://cbu01.alicdn.com/img/a.jpg",
            "",
            "https://cbu01.alicdn.com/img/b.jpg",
        ],
    )
    assert payload.reference_image_urls == [
        "https://cbu01.alicdn.com/img/a.jpg",
        "https://cbu01.alicdn.com/img/b.jpg",
    ]

    with pytest.raises(ValueError, match="http"):
        ProductKnowledgeCreate(
            product_name_en="Pump",
            raw_input_text="Pump description",
            target_market="US",
            reference_image_urls=["ftp://bad/img.jpg"],
        )


def test_variant_physical_parses_sqlite_json_strings() -> None:
    assert _variant_physical('{"physical": {"weight": {"value": 1}}}') == {
        "weight": {"value": 1}
    }
    assert _variant_physical("not-json") == {}
    assert _variant_physical(None) == {}
    assert _variant_physical({"physical": "oops"}) == {}
