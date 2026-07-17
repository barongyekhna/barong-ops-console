from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.modules.f_series.enrichment.models import FCategoryCandidate
from backend.app.modules.f_series.enrichment.service import import_candidate_to_k
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)
from backend.app.modules.k_series.product_knowledge.prompt_skills import (
    marketing_copy_instruction,
    selling_points_instruction,
)
from backend.app.modules.k_series.product_knowledge.router import (
    _product_full_ai_payload,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeCreate,
    ProductKnowledgeUpdate,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.service import get_product
from backend.app.modules.k_series.product_knowledge.structured_specs import (
    normalize_1688_structured_specs,
    normalize_operator_structured_specs,
)
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    _product_snapshot,
)


pytestmark = pytest.mark.unit


def _verified_specs() -> dict:
    result = normalize_1688_structured_specs(
        {
            "offer_id": "123456",
            "structured_attributes": [
                {"name": "光通量", "value": "800 lm"},
                {"attributeName": "色温(K)", "attributeValue": "2700-6500"},
                {"name": "电池类型", "value": "LiFePO4"},
                {"name": "电池容量", "value": "2200mAh"},
                {"name": "充电时间", "value": "6-8小时"},
                {"name": "续航时间", "value": "12 h"},
                {"name": "防护等级", "value": "IP65"},
                {"name": "产品尺寸", "value": "120×80×50 mm"},
                {"name": "净重", "value": "350 g"},
                {"name": "材质", "value": "ABS + aluminum"},
                {"name": "安装方式", "value": "地插"},
                {"name": "认证", "value": "CE, RoHS"},
                {"name": "输入电压", "value": "5V"},
                # Identity metadata is intentionally not a specification and
                # must not enter copy/image prompts through additional_specs.
                {"name": "品牌", "value": "ThirdParty"},
            ],
        },
        source_url="https://detail.1688.com/offer/123456.html",
    )
    assert result is not None
    return result


def test_1688_specs_are_normalized_with_original_evidence() -> None:
    specs = _verified_specs()

    assert specs["schema_version"] == "1.0"
    assert specs["source"] == {
        "platform": "1688",
        "offer_id": "123456",
        "url": "https://detail.1688.com/offer/123456.html",
    }
    assert specs["lumens"] == {
        "value": 800,
        "unit": "lm",
        "raw_value": "800 lm",
        "source_label": "光通量",
    }
    assert specs["color_temperature_k"]["value"] == {
        "min": 2700,
        "max": 6500,
    }
    assert specs["battery_capacity_mah"]["value"] == 2200
    assert specs["charge_time_h"]["value"] == {"min": 6, "max": 8}
    assert specs["runtime_h"]["value"] == 12
    assert specs["ip_rating"]["value"] == "IP65"
    assert specs["dimensions"]["length"]["value"] == 12
    assert specs["dimensions"]["unit"] == "cm"
    assert specs["weight"]["value"] == 0.35
    assert specs["certifications"]["value"] == ["CE", "RoHS"]
    assert specs["additional_specs"] == [
        {
            "key": "supplier_attribute_12b056a932",
            "label": "输入电压",
            "value": "5V",
            "raw_value": "5V",
        }
    ]
    assert "ThirdParty" not in str(specs)


def test_1688_specs_do_not_invent_missing_or_weak_claims() -> None:
    assert (
        normalize_1688_structured_specs(
            {"offer_id": "only-an-id"},
            source_url="https://detail.1688.com/offer/only-an-id.html",
        )
        is None
    )

    specs = normalize_1688_structured_specs(
        {
            "structured_attributes": [
                {"name": "防水等级", "value": "防水"},
                {"name": "续航时间", "value": "持久耐用"},
            ]
        }
    )
    assert specs is not None
    assert "ip_rating" not in specs
    assert "runtime_h" not in specs
    assert {item["label"] for item in specs["additional_specs"]} == {
        "防水等级",
        "续航时间",
    }


def test_label_unit_measurements_reject_option_lists_but_accept_scalar_and_range() -> None:
    specs = normalize_1688_structured_specs(
        {
            "structured_attributes": [
                {"name": "色温(K)", "value": "3色 3000/4500/6000"},
                {"name": "光通量(lm)", "value": "800"},
                {"name": "电池容量(mAh)", "value": "2200-2600"},
            ]
        }
    )

    assert specs is not None
    assert "color_temperature_k" not in specs
    assert specs["lumens"]["value"] == 800
    assert specs["battery_capacity_mah"]["value"] == {
        "min": 2200,
        "max": 2600,
    }
    assert [item["label"] for item in specs["additional_specs"]] == ["色温(K)"]


def test_measurements_never_promote_a_partial_multi_option_match() -> None:
    specs = normalize_1688_structured_specs(
        {
            "structured_attributes": [
                {"name": "色温", "value": "3色 3000/4500/6000K"},
                {"name": "光通量", "value": "400lm / 800lm"},
                {"name": "续航时间", "value": "3档 4/8/12小时"},
            ]
        }
    )

    assert specs is not None
    assert "color_temperature_k" not in specs
    assert specs["lumens"]["value"] == [400, 800]
    assert "runtime_h" not in specs
    assert [item["label"] for item in specs["additional_specs"]] == [
        "色温",
        "续航时间",
    ]


@pytest.mark.parametrize("schema", [ProductKnowledgeCreate, ProductKnowledgeUpdate])
def test_public_k_payloads_accept_only_operator_evidenced_specs(schema: type) -> None:
    manual = {
        "schema_version": "1.0",
        "source": {"platform": "operator"},
        "additional_specs": [
            {"key": "ignition", "label": "Ignition", "value": "Piezo"}
        ],
    }
    payload = {"structured_specs_json": manual}
    if schema is ProductKnowledgeCreate:
        payload["raw_input_text"] = "manual product"

    parsed = schema.model_validate(payload)
    assert parsed.structured_specs_json == {
        "schema_version": "1.0",
        "source": {
            "platform": "operator",
            "evidence_type": "operator_fact",
        },
        "additional_specs": [
            {
                "key": "ignition",
                "label": "Ignition",
                "value": "Piezo",
                "raw_value": "Piezo",
                "evidence": "operator_fact",
            }
        ],
    }

    supplier_payload = {"structured_specs_json": _verified_specs()}
    if schema is ProductKnowledgeCreate:
        supplier_payload["raw_input_text"] = "manual product"

    with pytest.raises(ValidationError, match="source.platform=operator"):
        schema.model_validate(supplier_payload)


def test_operator_specs_drop_blank_rows_and_reject_identity_fields() -> None:
    assert (
        normalize_operator_structured_specs(
            {
                "source": {"platform": "operator"},
                "additional_specs": [{"label": "", "value": ""}],
            }
        )
        is None
    )
    with pytest.raises(ValueError, match="identity"):
        normalize_operator_structured_specs(
            {
                "source": {"platform": "operator"},
                "additional_specs": [
                    {"label": "Manufacturer", "value": "ThirdParty"}
                ],
            }
        )
    with pytest.raises(ValueError, match="key must be unique"):
        normalize_operator_structured_specs(
            {
                "source": {"platform": "operator"},
                "additional_specs": [
                    {"key": "runtime", "label": "Runtime", "value": "2 h"},
                    {"key": "runtime", "label": "Battery Duration", "value": "3 h"},
                ],
            }
        )


def test_k_copy_and_selling_point_payloads_receive_the_same_verified_specs() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    specs = _verified_specs()
    product = KProductKnowledgeProduct(
        id=uuid4(),
        product_key="solar-light-spec-test",
        product_name_en="Solar path light",
        primary_keyword="solar path light",
        raw_input_text="Solar path light sourced from 1688",
        raw_input_language="en",
        canonical_language="en",
        structured_specs_json=specs,
    )
    db.add(product)
    db.commit()

    assert _product_snapshot(product)["structured_specs_json"] == specs
    assert _product_full_ai_payload(db, product)["structured_specs_json"] == specs
    assert "If a key is absent" in marketing_copy_instruction("dtc")
    assert "evidence_refs" in marketing_copy_instruction("dtc")
    assert "never infer, estimate, or fill it" in selling_points_instruction()


def test_f_to_k_transfer_preserves_structured_specs_unchanged() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE k_category_google ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, name_zh TEXT, "
                "full_path TEXT NOT NULL, parent_id TEXT, level INTEGER NOT NULL, "
                "is_leaf BOOLEAN NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO k_category_google "
                "(id, name, name_zh, full_path, parent_id, level, is_leaf) "
                "VALUES ('990991', 'Path Lights', '路径灯', "
                "'Home & Garden > Lighting > Path Lights', NULL, 3, 1)"
            )
        )
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    specs = _verified_specs()
    candidate = FCategoryCandidate(
        id=uuid4(),
        category_id="990991",
        category_path="Home & Garden > Lighting > Path Lights",
        title="太阳能路径灯",
        source="alibaba1688",
        source_url="https://detail.1688.com/offer/123456.html",
        price_cny=Decimal("12.50"),
        structured_specs_json=specs,
        status="approved",
    )
    db.add(candidate)
    db.commit()

    scope = KScopeContext(
        workspace_key="org_structured_specs",
        business_context="independent_store",
        scope_mode="production",
    )
    result = import_candidate_to_k(
        db,
        candidate=candidate,
        user=None,
        scope_context=scope,
    )
    product = db.get(KProductKnowledgeProduct, UUID(result["product_id"]))
    assert product is not None
    variant = db.scalar(
        select(KProductKnowledgeVariant).where(
            KProductKnowledgeVariant.product_id == product.id
        )
    )
    assert product.workspace_key == "org_structured_specs"
    assert product.business_context == "independent_store"
    assert product.scope_mode == "production"
    assert get_product(db, product_id=product.id, scope_context=scope).id == product.id
    assert product.structured_specs_json == specs
    assert product.google_product_category == "990991"
    assert product.sku == "PL-001"
    assert variant is not None
    assert variant.parent_sku == product.sku
    assert variant.variant_sku.startswith(f"{product.sku}-")
    assert variant.attributes_json == {"default_variant": True}
