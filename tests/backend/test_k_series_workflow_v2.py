from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User
from backend.app.modules.k_series.product_knowledge import (
    workflow_engine as workflow_module,
)
from backend.app.modules.k_series.product_knowledge.category_resolver import (
    bind_google_category_id,
)
from backend.app.modules.k_series.product_knowledge.constants import (
    TARGET_ORGANIZATION_NAME,
)
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
    KProductKnowledgeWorkflowExecution,
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
from backend.app.modules.p_series.upload import assemble as p_assemble
from backend.app.modules.p_series.upload import wc_categories
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
            "product_type": "simple_product",
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

    # The marketing-copy gate joined the chain after risk review; simulate
    # already-generated copy so the flow proceeds to the image gate.
    product.marketing_copy_json = {
        "channel": "dtc",
        "title": "Steel Pump Wholesale",
        "body_html": "<p>Generated marketing copy.</p>",
    }
    db.add(product)
    db.commit()

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
            variant_sku="PUMP-001-DEFAULT",
        ),
        scope_context=scope,
        user=user,
    )

    assert ready.status == "ready_for_export"
    assert ready.current_step == "export_p_series"
    assert KWorkflowStateMachineV2.current_state(ready, product) == "EXPORT_READY"

    product.ai_warnings_json = {
        **(product.ai_warnings_json or {}),
        "selling_points": {"review_status": "approved"},
    }
    # The K→P hard gate requires a bound category for the product channel.
    product.google_product_category = "7401"
    db.add(product)
    db.commit()

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


def test_v2_provider_failure_returns_blocked_partial_state_without_broken_session():
    db, user, scope, _engine, product = _setup_engine()
    attempts = {"serp_keyword_fetch": 0}

    def provider(key: ModuleExecutionKey, payload: dict):
        if key.step_name == "serp_keyword_fetch":
            attempts["serp_keyword_fetch"] += 1
            raise RuntimeError("serp provider unavailable")
        return _provider(key, payload)

    engine = KWorkflowOrchestratorV2(
        db,
        provider_client=provider,
        gate_resolver=_gate_resolver,
    )

    execution = engine.run(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowStartRequest(target_market="US"),
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )

    assert attempts["serp_keyword_fetch"] == 2
    assert execution.status == "blocked"
    assert execution.current_step == "serp_keyword_fetch"
    assert execution.error_report_json["code"] == "K_WORKFLOW_PROVIDER_STEP_FAILED"
    assert execution.error_report_json["details"]["db_rollback_reason"] == (
        "provider_step_failure"
    )
    assert execution.error_report_json["details"]["attempts"] == 2
    assert db.scalar(
        select(KProductKnowledgeWorkflowExecution).where(
            KProductKnowledgeWorkflowExecution.id == execution.id
        )
    )
    persisted_product = db.get(KProductKnowledgeProduct, product.id)
    assert persisted_product is not None
    assert persisted_product.deepseek_structured_output_json["confidence_score"] == 0.91


def test_v2_provider_step_retries_once_then_continues():
    db, user, scope, _engine, product = _setup_engine()
    attempts = {"ai_filter_chatgpt": 0}

    def provider(key: ModuleExecutionKey, payload: dict):
        if key.step_name == "ai_filter_chatgpt":
            attempts["ai_filter_chatgpt"] += 1
            if attempts["ai_filter_chatgpt"] == 1:
                raise RuntimeError("temporary chatgpt failure")
        return _provider(key, payload)

    engine = KWorkflowOrchestratorV2(
        db,
        provider_client=provider,
        gate_resolver=_gate_resolver,
    )

    execution = engine.run(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowStartRequest(target_market="US"),
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )

    assert attempts["ai_filter_chatgpt"] == 2
    assert execution.status == "blocked"
    assert execution.current_step == "risk_term_review_manual"
    assert execution.chatgpt_filter_result_json["cleaned_keywords"] == [
        "steel pump wholesale",
        "industrial steel pump",
    ]
    retry_logs = [
        item
        for item in execution.execution_gate_logs_json
        if item["gate"] == "workflow_resilience" and item["status"] == "retry"
    ]
    assert retry_logs
    assert retry_logs[0]["details"]["step"] == "ai_filter_chatgpt"


def test_v2_execute_provider_releases_router_transaction(monkeypatch):
    db, _user, _scope, _engine, _product = _setup_engine()
    engine = KWorkflowOrchestratorV2(db, gate_resolver=_gate_resolver)
    context = _gate_resolver(
        db,
        module_id="k.product_knowledge",
        key_requirements={"deepseek_enrichment": "deepseek"},
    )
    observed: dict[str, Any] = {}

    class FakeProviderSession:
        def __init__(self):
            self.invalidated = False

        def in_transaction(self):
            return True

        def in_nested_transaction(self):
            return False

        def invalidate(self):
            self.invalidated = True

    def provider_session_factory():
        session = FakeProviderSession()
        observed["provider_session"] = session
        return session

    monkeypatch.setattr(workflow_module, "SessionLocal", provider_session_factory)

    class FakeAIExecutionRouter:
        def __init__(self, session):
            self.db = session

        def execute(self, **_kwargs):
            assert self.db is not db
            assert self.db is observed["provider_session"]
            observed["provider_session_used"] = self.db.in_transaction()
            return {
                "product_name_en": "Router released steel pump",
                "product_type": "simple_product",
            }

    monkeypatch.setattr(workflow_module, "AIExecutionRouter", FakeAIExecutionRouter)

    result = engine._execute_provider(
        provider="deepseek",
        task_type="generate",
        key=context.key_for_step("deepseek_enrichment"),
        gate_context=context,
        payload={"task": "deepseek_enrichment"},
    )

    assert result["product_name_en"] == "Router released steel pump"
    assert observed["provider_session_used"] is True
    assert observed["provider_session"].invalidated is True
    assert not db.in_transaction()
    assert db.scalar(select(OrganizationRecord).limit(1)) is not None


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


def test_marketing_copy_keeps_google_id_and_p_builds_wc_category_hierarchy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, user, scope, engine, product = _setup_engine()
    category_path_text = (
        "Home & Garden > Lighting > Outdoor Lighting > Landscape Lighting > "
        "Pathway Lighting"
    )
    taxonomy_rows = [
        {
            "id": "1",
            "name": "Home & Garden",
            "full_path": "Home & Garden",
            "parent_id": None,
            "level": 1,
        },
        {
            "id": "2",
            "name": "Lighting",
            "full_path": "Home & Garden > Lighting",
            "parent_id": "1",
            "level": 2,
        },
        {
            "id": "3",
            "name": "Outdoor Lighting",
            "full_path": "Home & Garden > Lighting > Outdoor Lighting",
            "parent_id": "2",
            "level": 3,
        },
        {
            "id": "4",
            "name": "Landscape Lighting",
            "full_path": (
                "Home & Garden > Lighting > Outdoor Lighting > Landscape Lighting"
            ),
            "parent_id": "3",
            "level": 4,
        },
        {
            "id": "7401",
            "name": "Pathway Lighting",
            "full_path": category_path_text,
            "parent_id": "4",
            "level": 5,
        },
    ]
    db.execute(
        text(
            "CREATE TABLE k_category_google ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, full_path TEXT NOT NULL, "
            "parent_id TEXT, level INTEGER NOT NULL)"
        )
    )
    db.execute(
        text(
            "INSERT INTO k_category_google "
            "(id, name, full_path, parent_id, level) "
            "VALUES (:id, :name, :full_path, :parent_id, :level)"
        ),
        taxonomy_rows,
    )
    assert bind_google_category_id(db, product, "7401") is True
    product.regular_price = Decimal("19.99")
    product.price_currency = "USD"
    product.stock_status = "in_stock"
    product.inventory_quantity = 3
    db.add(product)
    db.commit()

    base_provider = engine.provider_client
    assert base_provider is not None

    def provider(key: ModuleExecutionKey, payload: dict[str, Any]) -> dict[str, Any]:
        if key.step_name == "marketing_copy_generation":
            return {
                "channel": "dtc",
                "product_page_copy": {
                    "marketing_copy": "Light every step with a clear path.",
                    "key_bullets": ["Focused outdoor pathway illumination"],
                },
                # A legacy/extra AI key must be treated only as a text hint.
                "google_product_category": category_path_text,
            }
        if key.step_name == "translate_zh":
            return {"content": "清晰照亮户外小径。"}
        output = base_provider(key, payload)
        if key.step_name == "deepseek_enrichment":
            return {
                **output,
                # Reproduces the original workflow/start corruption exactly.
                "google_product_category": category_path_text,
            }
        return output

    engine.provider_client = provider
    execution = engine.run(
        product_id=product.id,
        payload=ProductKnowledgeWorkflowStartRequest(target_market="US"),
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )

    assert execution.current_step == "risk_term_review_manual"
    assert product.google_product_category == "7401"
    assert product.category_hint == category_path_text
    assert product.field_diff_json["deepseek_enrichment"]["category_hint"] == {
        "before": None,
        "after": category_path_text,
    }

    generated = engine.generate_marketing_copy(
        product_id=product.id,
        scope_context=scope,
        request=None,  # type: ignore[arg-type]
        user=user,
    )
    assert generated.google_product_category == "7401"
    assert generated.category_hint == category_path_text

    monkeypatch.setattr(p_assemble, "_image_assets", lambda *args, **kwargs: [])
    monkeypatch.setattr(p_assemble, "_variants", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        p_assemble,
        "build_description_html",
        lambda *args, **kwargs: {
            "html": "<p>Light every step.</p>",
            "sections_emitted": [],
        },
    )

    created: list[dict[str, object]] = []
    next_term_id = iter((1001, 1002, 1003, 1004, 1005))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        created.append(body)
        term_id = next(next_term_id)
        return httpx.Response(
            201,
            json={"id": term_id, **body},
        )

    settings = SimpleNamespace(
        app_env="development",
        wp_base_url="https://shop.example.test",
        wp_app_user="category-bot",
        wp_app_password="example-app-password",
        wp_request_timeout_seconds=1.0,
        wp_request_max_attempts=1,
    )
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as client:

        def ensure_path(actual_db, path):
            return wc_categories.ensure_wc_category_path(
                actual_db,
                path,
                client=client,
                settings=settings,  # type: ignore[arg-type]
                sleep=lambda _: None,
            )

        monkeypatch.setattr(p_assemble, "ensure_wc_category_path", ensure_path)
        package = p_assemble.assemble_upload_package(
            db,
            generated,
            base_url="https://console.example.test",
        )

        # A product polluted before this fix is deterministically repaired on
        # its next dispatch; the populated WC leaf cache avoids another POST.
        generated.google_product_category = category_path_text
        generated.category_review_needed = True
        db.add(generated)
        db.commit()
        legacy_package = p_assemble.assemble_upload_package(
            db,
            generated,
            base_url="https://console.example.test",
        )

    assert package.product.category.google_product_category == "7401"
    assert package.product.category.path == [
        "Home & Garden",
        "Lighting",
        "Outdoor Lighting",
        "Landscape Lighting",
        "Pathway Lighting",
    ]
    assert package.product.category.wc_category_id == 1005
    assert legacy_package.product.category.google_product_category == "7401"
    assert legacy_package.product.category.wc_category_id == 1005
    assert generated.google_product_category == "7401"
    assert generated.category_review_needed is False
    assert [(item["name"], item["parent"]) for item in created] == [
        ("Home & Garden", 0),
        ("Lighting", 1001),
        ("Outdoor Lighting", 1002),
        ("Landscape Lighting", 1003),
        ("Pathway Lighting", 1004),
    ]
    assert db.execute(
        text(
            "SELECT wc_term_id FROM k_category_wc_map "
            "WHERE google_id = '7401'"
        )
    ).scalar_one() == 1005

    # Old executions may already contain the polluted value in their saved
    # field diff. A rollback must recover only the original taxonomy id.
    generated.google_product_category = category_path_text
    deepseek_diff = dict(generated.field_diff_json["deepseek_enrichment"])
    deepseek_diff["google_product_category"] = {
        "before": "7401",
        "after": category_path_text,
    }
    generated.field_diff_json = {
        **generated.field_diff_json,
        "deepseek_enrichment": deepseek_diff,
    }
    workflow_module._rollback_deepseek_product_fields(db, generated)

    assert generated.google_product_category == "7401"
    assert generated.category_hint is None
