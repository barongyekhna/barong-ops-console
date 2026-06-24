from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
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
    KWorkflowOrchestratorV2,
    KWorkflowStateMachineV2,
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
    if key.step_name == "deepseek_enrichment":
        return {
            "product_name_en": "DeepSeek enriched steel pump",
            "product_type": "Industrial pump",
            "short_description_en": "AI structured steel pump for wholesale buyers.",
            "confidence_score": 0.91,
        }
    if key.step_name == "serp_keyword_fetch":
        return {
            "keywords": ["steel pump wholesale", "industrial steel pump"],
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


def _setup_engine():
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
        product_name_en="Industrial steel pump",
        raw_input_text="Industrial steel pump for wholesale buyers",
        raw_input_language="en",
        canonical_language="en",
        dimensions_json={"length": 10, "unit": "cm"},
        weight_json={"value": 2, "unit": "kg"},
    )
    db.add(product)
    db.commit()
    engine = KWorkflowOrchestratorV2(
        db,
        provider_client=_provider,
        gate_resolver=_gate_resolver,
    )
    scope = KScopeContext(
        workspace_key=ORG_ID,
        business_context="independent_store",
        scope_mode="production",
    )
    return db, user, scope, engine, product


def _start_v2_workflow():
    db, user, scope, engine, product = _setup_engine()
    execution = engine.run(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowStartRequest(target_market="US"),
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )
    return db, user, scope, engine, product, execution


def test_v2_closed_loop_runs_to_risk_gate_then_exports_after_manual_gates():
    db, user, scope, engine, product, execution = _start_v2_workflow()

    assert execution.status == "blocked"
    assert execution.current_step == "risk_term_review_manual"
    assert product.deepseek_structured_output_json["confidence_score"] == 0.91
    assert product.product_name_en == "DeepSeek enriched steel pump"
    assert KWorkflowStateMachineV2.current_state(execution, product) == (
        "RISK_PENDING_REVIEW"
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

    assert reviewed.status == "blocked"
    assert reviewed.current_step == "image_binding"
    assert reviewed.final_keyword_set_json["primary_keywords"] == [
        "steel pump wholesale"
    ]
    assert KWorkflowStateMachineV2.current_state(reviewed, product) == "UNIT_NORMALIZED"

    ready = engine.bind_image_asset(
        product_id=product.id,
        payload=ProductKnowledgeImageBindRequest(
            source_type="i_system_asset",
            i_system_image_asset_id="i-img-closed-loop",
        ),
        scope_context=scope,
        user=user,
    )

    assert ready.status == "ready_for_export"
    assert ready.current_step == "export_p_series"
    assert KWorkflowStateMachineV2.current_state(ready, product) == "EXPORT_READY"

    exported, report = engine.export_payloads(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowExportRequest(execution_id=execution.id),
        scope_context=scope,
        user=user,
    )

    assert exported.status == "exported"
    assert exported.current_step == "export_seo"
    assert KWorkflowStateMachineV2.current_state(exported, product) == "EXPORTED"
    assert {"export_p_series", "export_gmc", "export_seo"}.issubset(
        {item["step"] for item in exported.trace_json}
    )
    assert set(report.export_payloads or {}) == {
        "p_series_payload",
        "gmc_feed_structure",
        "seo_keyword_pack",
    }
    assert db.get(
        KProductKnowledgeMediaAsset,
        UUID(exported.image_binding_json["asset_id"]),
    )


def test_v2_pause_resume_does_not_bypass_manual_risk_gate():
    _db, user, scope, engine, product, execution = _start_v2_workflow()

    paused = engine.pause(workflow_id=execution.id, scope_context=scope, user=user)
    assert paused.status == "blocked"
    assert paused.error_report_json["code"] == "WORKFLOW_PAUSED"

    resumed = engine.resume(
        workflow_id=execution.id,
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )

    assert resumed.status == "blocked"
    assert resumed.current_step == "risk_term_manual_review"
    assert resumed.error_report_json["code"] == "RISK_REVIEW_REQUIRED"
    assert product.primary_keyword is None


def test_v2_rollback_and_retry_continue_from_requested_step():
    _db, user, scope, engine, product, execution = _start_v2_workflow()

    rolled_back = engine.rollback(
        workflow_id=execution.id,
        step="ai_filter_claude_opus",
        scope_context=scope,
        user=user,
    )

    assert rolled_back.status == "blocked"
    assert rolled_back.current_step == "ai_filter_claude_opus"
    assert rolled_back.claude_filter_result_json is None
    assert rolled_back.chatgpt_filter_result_json is not None
    assert KWorkflowStateMachineV2.current_state(rolled_back, product) == (
        "CHATGPT_FILTERED"
    )

    retried = engine.retry(
        workflow_id=execution.id,
        step="ai_filter_claude_opus",
        payload=None,
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )

    assert retried.status == "blocked"
    assert retried.current_step == "risk_term_review_manual"
    assert retried.claude_filter_result_json["risk_keywords"][0]["term"] == (
        "best guaranteed pump"
    )
    assert KWorkflowStateMachineV2.current_state(retried, product) == (
        "RISK_PENDING_REVIEW"
    )
