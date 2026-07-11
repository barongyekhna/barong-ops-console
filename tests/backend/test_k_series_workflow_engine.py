from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.k_series.product_knowledge.constants import (
    TARGET_ORGANIZATION_NAME,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeRiskTerm,
    KProductKnowledgeVariant,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeImageBindRequest,
    ProductKnowledgeRiskReviewDecision,
    ProductKnowledgeRiskReviewRequest,
    ProductKnowledgeWorkflowExportRequest,
    ProductKnowledgeWorkflowStartRequest,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    KWorkflowOrchestratorV1,
)
from backend.app.services.module_execution_gate import (
    ModuleExecutionContext,
    ModuleExecutionKey,
)

pytestmark = pytest.mark.unit

ORG_ID = "org_11111111111111111111111111111111"


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _gate_resolver(_db, *, module_id, key_requirements, **_kwargs):
    return ModuleExecutionContext(
        org_id=ORG_ID,
        requested_module_id=module_id,
        control_module_id=module_id,
        keys={
            step: ModuleExecutionKey(
                step_name=step,
                key_alias=alias,
                key_id=f"key_{alias}",
                name=alias,
                url=f"https://{alias}.example",
                header_name="Authorization",
                header_value="Bearer redacted",
            )
            for step, alias in key_requirements.items()
        },
    )


def _provider(key: ModuleExecutionKey, _payload: dict):
    if key.step_name == "serp_keyword_fetch":
        return {
            "keywords": [
                "steel pump wholesale",
                "industrial steel pump",
                "steel pump supplier",
            ],
            "competitors": ["competitor.example"],
            "organic_results": [
                {
                    "title": "Industrial steel pump supplier",
                    "url": "https://competitor.example/pump",
                }
            ],
        }
    if key.step_name == "ai_filter_chatgpt":
        return {
            "cleaned_keywords": ["steel pump wholesale", "industrial steel pump"],
            "filtered_keywords": ["steel pump wholesale"],
            "rejected_keywords": ["cheap miracle pump"],
            "rationale": "Removed unsupported claims.",
        }
    if key.step_name == "ai_filter_claude_opus":
        return {
            "final_keywords": [
                "steel pump wholesale",
                "industrial steel pump",
                "custom industrial steel pump supplier",
            ],
            "high_value_keywords": ["steel pump wholesale"],
            "low_value_keywords": ["custom industrial steel pump supplier"],
            "risk_keywords": [{"term": "best guaranteed pump", "reason": "claim"}],
        }
    raise AssertionError(f"unexpected provider step {key.step_name}")


def _workflow_ready_for_image():
    db = _session()
    user = User(id=1, username="owner", password_hash="x", role="owner", is_active=True)
    db.add(
        OrganizationRecord(
            org_id=ORG_ID,
            org_name=TARGET_ORGANIZATION_NAME,
            org_type="store",
            owner_user_id="1",
            status="active",
            metadata_json={},
        )
    )
    product = KProductKnowledgeProduct(
        id=uuid4(),
        workspace_key=ORG_ID,
        business_context="independent_store",
        scope_mode="production",
        organization_name=TARGET_ORGANIZATION_NAME,
        product_key="pump-001",
        parent_sku="PUMP-001",
        sku="PUMP-001",
        product_type="simple_product",
        product_name_en="Industrial steel pump",
        raw_input_text="Industrial steel pump for wholesale buyers",
        raw_input_language="en",
        canonical_language="en",
        dimensions_json={"length": 10, "unit": "cm"},
        weight_json={"value": 2, "unit": "kg"},
    )
    db.add(product)
    db.add(
        KProductKnowledgeVariant(
            id=uuid4(),
            product_id=product.id,
            parent_sku="PUMP-001",
            variant_sku="PUMP-001-DEFAULT",
            variant_hash="DEFAULT",
            attributes_json={"default_variant": True},
            image_folder="images/pump-001/PUMP-001-DEFAULT",
        )
    )
    db.commit()

    engine = KWorkflowOrchestratorV1(
        db,
        provider_client=_provider,
        gate_resolver=_gate_resolver,
    )
    scope = KScopeContext(
        workspace_key=ORG_ID,
        business_context="independent_store",
        scope_mode="production",
    )
    execution = engine.start_pipeline(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowStartRequest(target_market="US"),
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )
    reviewed = engine.review_risk_terms(
        product_id=product.id,
        payload=ProductKnowledgeRiskReviewRequest(
            execution_id=execution.id,
            decisions=[
                ProductKnowledgeRiskReviewDecision(
                    term="best guaranteed pump",
                    decision="approve",
                )
            ],
        ),
        scope_context=scope,
        user=user,
    )
    return db, user, scope, engine, product, reviewed


def test_k_workflow_blocks_until_manual_risk_and_image_gates_pass():
    db = _session()
    user = User(id=1, username="owner", password_hash="x", role="owner", is_active=True)
    db.add(
        OrganizationRecord(
            org_id=ORG_ID,
            org_name=TARGET_ORGANIZATION_NAME,
            org_type="store",
            owner_user_id="1",
            status="active",
            metadata_json={},
        )
    )
    product = KProductKnowledgeProduct(
        id=uuid4(),
        workspace_key=ORG_ID,
        business_context="independent_store",
        scope_mode="production",
        organization_name=TARGET_ORGANIZATION_NAME,
        product_key="pump-001",
        parent_sku="PUMP-001",
        sku="PUMP-001",
        product_type="simple_product",
        product_name_en="Industrial steel pump",
        raw_input_text="Industrial steel pump for wholesale buyers",
        raw_input_language="en",
        canonical_language="en",
        dimensions_json={"length": 10, "unit": "cm"},
        weight_json={"value": 2, "unit": "kg"},
    )
    db.add(product)
    db.add(
        KProductKnowledgeVariant(
            id=uuid4(),
            product_id=product.id,
            parent_sku="PUMP-001",
            variant_sku="PUMP-001-DEFAULT",
            variant_hash="DEFAULT",
            attributes_json={"default_variant": True},
            image_folder="images/pump-001/PUMP-001-DEFAULT",
        )
    )
    db.commit()

    engine = KWorkflowOrchestratorV1(
        db,
        provider_client=_provider,
        gate_resolver=_gate_resolver,
    )
    scope = KScopeContext(
        workspace_key=ORG_ID,
        business_context="independent_store",
        scope_mode="production",
    )

    execution = engine.start_pipeline(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowStartRequest(target_market="US"),
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )

    assert execution.status == "blocked"
    assert execution.current_step == "risk_term_review_manual"
    assert execution.chatgpt_filter_result_json["cleaned_keywords"]
    assert execution.claude_filter_result_json["risk_keywords"][0]["term"] == (
        "best guaranteed pump"
    )
    assert db.scalar(select(KProductKnowledgeRiskTerm)).status == "candidate"

    reviewed = engine.review_risk_terms(
        product_id=product.id,
        payload=ProductKnowledgeRiskReviewRequest(
            execution_id=execution.id,
            decisions=[
                ProductKnowledgeRiskReviewDecision(
                    term="best guaranteed pump",
                    decision="approve",
                )
            ],
        ),
        scope_context=scope,
        user=user,
    )

    assert reviewed.status == "blocked"
    assert reviewed.current_step == "image_handling"
    assert reviewed.final_keyword_set_json["primary_keywords"] == [
        "steel pump wholesale"
    ]
    assert reviewed.unit_conversion_json["normalized_fields"]["dimensions_json"][
        "normalized"
    ]["length_inch"] == 3.937

    asset = KProductKnowledgeMediaAsset(
        id=uuid4(),
        product_id=product.id,
        asset_type="image",
        asset_role="main",
        status="available",
        review_status="not_applicable",
        object_key="images/pump-001/PUMP-001-DEFAULT/main.jpg",
        file_url_placeholder="https://cdn.example/main.jpg",
        source="manual_upload_image",
        variant_sku="PUMP-001-DEFAULT",
        metadata_json={
            "filename": "main.jpg",
            "source_type": "manual_upload_image",
            "variant_sku": "PUMP-001-DEFAULT",
        },
    )
    db.add(asset)
    db.flush()

    ready = engine.bind_image_asset(
        product_id=product.id,
        payload=ProductKnowledgeImageBindRequest(
            source_type="manual_upload_image",
            asset_id=asset.id,
            variant_sku="PUMP-001-DEFAULT",
        ),
        scope_context=scope,
        user=user,
    )
    assert ready.status == "ready_for_export"

    product.ai_warnings_json = {
        **(product.ai_warnings_json or {}),
        "selling_points": {"review_status": "approved"},
    }
    # The K→P hard gate requires a bound category for the product channel.
    product.google_product_category = "Hardware > Pumps"
    db.add(product)
    db.commit()

    exported, report = engine.export_payloads(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowExportRequest(execution_id=execution.id),
        scope_context=scope,
        user=user,
    )

    assert exported.status == "exported"
    assert set(report.export_payloads or {}) == {
        "p_series_payload",
        "gmc_feed_structure",
        "seo_keyword_pack",
    }
    assert report.risk_approval_log["approved"] is True


def test_k_workflow_binds_i_system_image_asset_without_k_review():
    db, user, scope, engine, product, execution = _workflow_ready_for_image()

    ready = engine.bind_image_asset(
        product_id=product.id,
        payload=ProductKnowledgeImageBindRequest(
            source_type="i_system_asset",
            i_system_image_asset_id="i-img-001",
            variant_sku="PUMP-001-DEFAULT",
        ),
        scope_context=scope,
        user=user,
    )

    assert ready.status == "ready_for_export"
    assert ready.image_binding_json["source_type"] == "i_system_asset"
    assert ready.image_binding_json["i_system_image_asset_id"] == "i-img-001"
    assert ready.image_binding_json["variant_sku"] == "PUMP-001-DEFAULT"
    assert ready.image_binding_json["asset_id"]
    assert execution.image_binding_json == ready.image_binding_json

    asset = db.scalar(
        select(KProductKnowledgeMediaAsset).where(
            KProductKnowledgeMediaAsset.product_id == product.id,
            KProductKnowledgeMediaAsset.source == "i_system_asset",
        )
    )
    assert asset is not None
    assert asset.review_status == "i_system_managed"
    assert asset.storage_provider == "i_series"
    assert asset.metadata_json["k_image_ai_generation_allowed"] is False
    assert asset.metadata_json["k_image_review_allowed"] is False
