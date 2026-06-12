import inspect
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel

from backend.app.modules.k_series.product_knowledge import schemas


def test_product_knowledge_create_accepts_minimum_fields() -> None:
    payload = schemas.ProductKnowledgeCreate(
        product_key=" sku-001 ",
        raw_input_text="Unstructured product facts.",
        raw_input_language=" EN ",
    )

    assert payload.product_key == "sku-001"
    assert payload.raw_input_language == "en"
    assert payload.canonical_language == "en"
    assert payload.attributes == []
    assert payload.keywords == []
    assert payload.risk_terms == []


def test_product_knowledge_update_supports_partial_update() -> None:
    payload = schemas.ProductKnowledgeUpdate(product_name_en="Sample product")

    assert payload.model_dump(exclude_unset=True) == {
        "product_name_en": "Sample product"
    }
    assert schemas.ProductKnowledgeUpdate().model_dump(exclude_unset=True) == {}


def test_product_read_and_list_item_expose_basic_fields() -> None:
    now = datetime.now(timezone.utc)
    product_id = uuid4()

    read = schemas.ProductKnowledgeRead(
        id=product_id,
        product_key="sku-001",
        product_status="draft",
        review_status="draft",
        canonical_language="en",
        raw_input_text="Raw facts",
        raw_input_language="en",
        product_name_en="Sample product",
        brand_name=None,
        manufacturer=None,
        product_type=None,
        short_description_en=None,
        long_description_en=None,
        primary_use_case_en=None,
        target_customer_en=None,
        sku=None,
        workspace_key="default_independent_store",
        business_context="independent_store",
        scope_mode="adapter_pending",
        created_at=now,
        updated_at=now,
    )
    list_item = schemas.ProductKnowledgeListItem(
        id=product_id,
        product_key="sku-001",
        sku=None,
        product_name_en="Sample product",
        brand_name=None,
        product_type=None,
        product_status="draft",
        review_status="draft",
        canonical_language="en",
        workspace_key="default_independent_store",
        business_context="independent_store",
        scope_mode="adapter_pending",
        created_at=now,
        updated_at=now,
    )

    assert read.id == product_id
    assert read.workspace_key == "default_independent_store"
    assert list_item.product_key == "sku-001"
    assert list_item.scope_mode == "adapter_pending"


def test_archive_request_and_child_patch_schemas_can_be_created() -> None:
    archive = schemas.ArchiveProductKnowledgeRequest(reason="Duplicate record")
    attributes = schemas.ProductKnowledgeAttributePatch(
        items=[
            schemas.ProductKnowledgeAttributeItem(
                attribute_key="material",
                attribute_value_text="stainless steel",
            )
        ]
    )
    keywords = schemas.ProductKnowledgeKeywordPatch(
        items=[
            schemas.ProductKnowledgeKeywordItem(
                keyword_text=" commercial kettle ",
                keyword_type="primary",
                language_code=" EN ",
            )
        ]
    )
    risk_terms = schemas.ProductKnowledgeRiskTermPatch(
        items=[
            schemas.ProductKnowledgeRiskTermItem(
                term_en="medical grade",
                risk_type="regulated_claim",
            )
        ]
    )

    assert archive.reason == "Duplicate record"
    assert attributes.items[0].attribute_key == "material"
    assert keywords.items[0].keyword_text == "commercial kettle"
    assert keywords.items[0].language_code == "en"
    assert risk_terms.items[0].term_en == "medical grade"


def test_schemas_do_not_define_provider_secret_fields() -> None:
    sensitive_name_parts = (
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "password",
        "credential",
    )
    schema_classes = [
        value
        for value in vars(schemas).values()
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value.__module__ == schemas.__name__
    ]

    assert schema_classes
    for schema_class in schema_classes:
        for field_name in schema_class.model_fields:
            normalized = field_name.lower()
            assert not any(part in normalized for part in sensitive_name_parts)
