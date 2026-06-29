from __future__ import annotations

from base64 import b64decode
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers

from backend.app.db.base import Base
from backend.app.modules.k_series.product_knowledge.errors import KConflictError
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeAIEvent,
    KProductKnowledgeAttribute,
    KProductKnowledgeKeyword,
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeResearchRun,
    KProductKnowledgeReviewItem,
    KProductKnowledgeRiskTerm,
    KProductKnowledgeTranslation,
    KProductKnowledgeVariant,
    KProductKnowledgeVersion,
    KProductKnowledgeWorkflowExecution,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeCreate,
    ProductKnowledgeVariantItem,
)
import backend.app.modules.k_series.product_knowledge.router as product_router
from backend.app.modules.k_series.product_knowledge.router import (
    _active_keyword_snapshot,
    _ensure_product_ready_for_approval,
    _claim_product_create_idempotency,
    _complete_product_create_idempotency,
    _discard_product_create_idempotency,
    download_media_asset_file,
    _gate_error,
    _product_readiness,
    _require_k_permission,
    _selling_points_snapshot,
    _store_image_review_snapshot,
    _store_keyword_review_snapshot,
    upload_product_media_asset,
    _workflow_error,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.modules.k_series.product_knowledge.service import (
    create_product,
    delete_product,
)
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    KWorkflowExecutionError,
)
from backend.app.services.module_execution_gate import (
    API_KEY_BINDING_MISSING_CODE,
    ModuleExecutionGateError,
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


PNG_1X1 = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
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

    assert UUID(product.product_key).version == 4
    assert product.product_type == "variable_product"
    assert product.parent_sku == "PUMP-FAMILY"
    assert len(variants) == 2
    assert all(item.variant_sku.startswith("PUMP-FAMILY-") for item in variants)
    assert all(item.image_folder.startswith(f"images/{product.product_key}/") for item in variants)


def test_media_upload_persists_real_image_bytes_and_downloads_inline(
    monkeypatch,
    tmp_path,
) -> None:
    db = _session()
    product = create_product(
        db,
        payload=ProductKnowledgeCreate(
            parent_sku="media family",
            product_name_en="Media family",
            raw_input_text="Media family description",
            target_market="US",
        ),
        scope_context=_scope(),
    )
    variant = db.scalar(
        select(KProductKnowledgeVariant).where(
            KProductKnowledgeVariant.product_id == product.id
        )
    )
    assert variant is not None
    monkeypatch.setenv("K_PRODUCT_MEDIA_STORAGE_DIR", str(tmp_path))

    upload = UploadFile(
        BytesIO(PNG_1X1),
        filename="preview.png",
        headers=Headers({"content-type": "image/png"}),
    )
    request = SimpleNamespace(state=SimpleNamespace(org_id="org_test"))
    user = SimpleNamespace(id=uuid4())

    uploaded = upload_product_media_asset(
        product_id=product.id,
        request=request,
        variant_sku=variant.variant_sku,
        asset_role="main",
        file=upload,
        db=db,
        user=user,
    )

    row = db.get(KProductKnowledgeMediaAsset, UUID(uploaded.id))
    assert row is not None
    assert row.storage_provider == "local_filesystem"
    assert row.mime_type == "image/png"
    assert row.file_size == len(PNG_1X1)
    assert row.metadata_json["direct_binary_upload"] is True
    assert "db_content_base64" not in row.metadata_json
    stored_path = tmp_path / row.object_key
    assert stored_path.read_bytes() == PNG_1X1

    response = download_media_asset_file(
        asset_id=row.id,
        request=request,
        db=db,
        user=user,
    )

    assert response.media_type == "image/png"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "preview.png" in response.headers["content-disposition"]
    assert response.path == stored_path
    assert stored_path.read_bytes() == PNG_1X1


def test_create_validates_sku_uniqueness_before_insert() -> None:
    db = _session()
    first_payload = ProductKnowledgeCreate(
        parent_sku="pump family",
        product_name_en="Pump family",
        raw_input_text="Pump family description",
        target_market="US",
    )
    duplicate_payload = ProductKnowledgeCreate(
        parent_sku="PUMP-FAMILY",
        product_name_en="Duplicate pump family",
        raw_input_text="Duplicate pump family description",
        target_market="US",
    )

    create_product(db, payload=first_payload, scope_context=_scope())

    with pytest.raises(KConflictError, match="SKU already exists"):
        create_product(db, payload=duplicate_payload, scope_context=_scope())


def test_create_rejects_manual_variant_sku() -> None:
    with pytest.raises(ValueError, match="variant_sku is auto-generated"):
        ProductKnowledgeCreate(
            parent_sku="PARENT-001",
            product_name_en="Pump",
            product_type="variable_product",
            raw_input_text="Pump description",
            target_market="US",
            variants=[
                ProductKnowledgeVariantItem(
                    variant_sku="MANUAL-SKU",
                    color="blue",
                ),
            ],
        )


def test_product_create_idempotency_reuses_completed_record() -> None:
    cache_key = f"test-product-create-{uuid4()}"
    fingerprint = "payload-fingerprint"
    product_id = uuid4()
    first_record = _claim_product_create_idempotency(
        cache_key=cache_key,
        fingerprint=fingerprint,
    )
    try:
        assert first_record.product_id is None
        _complete_product_create_idempotency(
            cache_key=cache_key,
            record=first_record,
            product_id=product_id,
        )
    finally:
        first_record.lock.release()

    second_record = _claim_product_create_idempotency(
        cache_key=cache_key,
        fingerprint=fingerprint,
    )
    try:
        assert second_record.product_id == product_id
    finally:
        _discard_product_create_idempotency(
            cache_key=cache_key,
            record=second_record,
        )
        second_record.lock.release()


def test_delete_product_requires_key_and_cascades_product_records() -> None:
    db = _session()
    payload = ProductKnowledgeCreate(
        parent_sku="delete family",
        product_name_en="Delete family",
        product_type="variable_product",
        raw_input_text="Delete family description",
        target_market="US",
        variants=[
            ProductKnowledgeVariantItem(
                color="black",
                size="M",
                attributes={"delete_check": True},
            ),
        ],
    )
    product = create_product(db, payload=payload, scope_context=_scope())
    variant = db.scalar(
        select(KProductKnowledgeVariant).where(
            KProductKnowledgeVariant.product_id == product.id
        )
    )
    assert variant is not None

    research_run = KProductKnowledgeResearchRun(
        product_id=product.id,
        run_type="keyword_research",
        target_market="US",
        target_language="en",
    )
    db.add(research_run)
    db.flush()
    db.add_all(
        [
            KProductKnowledgeAttribute(
                product_id=product.id,
                attribute_key="delete_check",
                attribute_value_text="yes",
            ),
            KProductKnowledgeKeyword(
                product_id=product.id,
                keyword_text="delete check",
                keyword_type="primary",
                language_code="en",
                source="manual",
                status="candidate",
            ),
            KProductKnowledgeRiskTerm(
                product_id=product.id,
                term_en="restricted",
                risk_type="compliance",
                source="manual",
                status="candidate",
            ),
            KProductKnowledgeMediaAsset(
                product_id=product.id,
                variant_id=variant.id,
                variant_sku=variant.variant_sku,
                asset_type="image",
                asset_role="main",
            ),
            KProductKnowledgeAIEvent(
                product_id=product.id,
                research_run_id=research_run.id,
                event_type="selling_points",
                provider="chatgpt",
                status="succeeded",
            ),
            KProductKnowledgeWorkflowExecution(
                product_id=product.id,
                organization_name=product.organization_name,
                workspace_key=product.workspace_key,
                business_context=product.business_context,
                scope_mode=product.scope_mode,
                target_market="US",
                status="created",
                current_step="product_ingestion",
                trace_json=[{"step": "product_ingestion", "status": "created"}],
                execution_gate_logs_json=[],
            ),
            KProductKnowledgeVersion(
                product_id=product.id,
                version_number=1,
                change_type="create",
                change_source="test",
            ),
            KProductKnowledgeTranslation(
                product_id=product.id,
                language_code="en",
                translation_type="title",
                source_text_hash="hash",
                translated_payload_json={"title": "Delete family"},
            ),
            KProductKnowledgeReviewItem(
                product_id=product.id,
                review_type="manual",
                title="Delete review item",
            ),
        ]
    )
    db.commit()

    with pytest.raises(KConflictError, match="Product key confirmation"):
        delete_product(
            db,
            product_id=product.id,
            product_key="wrong-key",
            scope_context=_scope(),
        )

    counts = delete_product(
        db,
        product_id=product.id,
        product_key=product.product_key,
        scope_context=_scope(),
    )

    assert counts["products"] == 1
    assert counts["variants"] == 1
    assert counts["keywords"] == 1
    assert counts["risk_terms"] == 1
    assert counts["media_references"] == 1
    assert counts["ai_events"] == 1
    assert counts["workflow_traces"] == 1
    assert db.scalar(
        select(KProductKnowledgeProduct).where(
            KProductKnowledgeProduct.id == product.id
        )
    ) is None
    for model in (
        KProductKnowledgeAttribute,
        KProductKnowledgeKeyword,
        KProductKnowledgeRiskTerm,
        KProductKnowledgeMediaAsset,
        KProductKnowledgeAIEvent,
        KProductKnowledgeWorkflowExecution,
        KProductKnowledgeResearchRun,
        KProductKnowledgeVariant,
    ):
        assert (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.product_id == product.id)
            )
            == 0
        )


def test_product_readiness_requires_submitted_snapshots_and_detects_keyword_drift() -> None:
    db = _session()
    product = create_product(
        db,
        payload=ProductKnowledgeCreate(
            parent_sku="ready family",
            product_name_en="Ready family",
            raw_input_text="Ready family description",
            target_market="US",
        ),
        scope_context=_scope(),
    )
    variant = db.scalar(
        select(KProductKnowledgeVariant).where(
            KProductKnowledgeVariant.product_id == product.id
        )
    )
    assert variant is not None

    keyword = KProductKnowledgeKeyword(
        product_id=product.id,
        keyword_text="ready keyword",
        keyword_type="primary",
        language_code="en",
        source="manual",
        status="approved",
    )
    db.add_all(
        [
            keyword,
            KProductKnowledgeKeyword(
                product_id=product.id,
                keyword_text="stable keyword",
                keyword_type="secondary",
                language_code="en",
                source="manual",
                status="approved",
            ),
        ]
    )
    for index in range(5):
        db.add(
            KProductKnowledgeMediaAsset(
                product_id=product.id,
                variant_id=variant.id,
                variant_sku=variant.variant_sku,
                asset_type="image",
                asset_role="main",
                object_key=f"ready/{index}.jpg",
                source="manual_upload_image",
                status="available",
                review_status="not_applicable",
            )
        )
    db.flush()

    selling_points_payload = {
        "bullets": [
            {
                "category": "conversion",
                "importance_score": 1,
                "text": "Ready selling point",
            }
        ],
        "seo_keywords": ["ready keyword"],
        "market_tags": ["US"],
        "confidence_score": 1,
        "source": "manual_review",
        "marketing_copy": "Ready copy",
        "translated_version": "Ready translated copy",
        "chinese_translation": "已确认卖点",
        "target_language": "en",
        "product_id": str(product.id),
        "review_status": "approved",
    }
    product.ai_warnings_json = {"selling_points": selling_points_payload}
    db.add(product)
    db.flush()

    selling_points_snapshot = _selling_points_snapshot(product)
    product.ai_warnings_json = {
        **product.ai_warnings_json,
        "selling_points_review": {
            "status": "approved",
            "approved_at": "2026-06-27T00:00:00+00:00",
            "selling_points_digest": selling_points_snapshot["digest"],
            "bullet_count": selling_points_snapshot["count"],
        },
    }
    db.add(product)
    db.flush()
    keyword_state = _store_keyword_review_snapshot(
        db,
        product=product,
        user=SimpleNamespace(id=uuid4()),
    )
    assert keyword_state.submitted is True
    assert keyword_state.count == 2
    image_state = _store_image_review_snapshot(
        db,
        product=product,
        user=SimpleNamespace(id=uuid4()),
    )
    assert image_state.submitted is True

    readiness = _product_readiness(db, product)
    assert readiness.ready is True
    _ensure_product_ready_for_approval(db, product)

    keyword.status = "removed"
    db.add(keyword)
    db.flush()

    readiness_after_keyword_change = _product_readiness(db, product)
    assert readiness_after_keyword_change.ready is False
    assert readiness_after_keyword_change.keywords.dirty is True
    with pytest.raises(HTTPException) as exc_info:
        _ensure_product_ready_for_approval(db, product)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PRODUCT_SECTIONS_NOT_SUBMITTED"


def test_k_permission_allows_super_admin_and_assigned_roles(monkeypatch) -> None:
    def permission_info(_db, _user, request=None):
        del request
        return SimpleNamespace(
            is_owner_full_access=False,
            permission_keys=["k.product_knowledge.update"],
        )

    monkeypatch.setattr(
        product_router,
        "resolve_current_user_permission_info",
        permission_info,
    )
    dependency = _require_k_permission("k.product_knowledge.update")
    super_admin = SimpleNamespace(role="super_admin")
    operator = SimpleNamespace(role="operator")

    assert dependency(request=SimpleNamespace(), db=object(), user=super_admin) is super_admin
    assert dependency(request=SimpleNamespace(), db=object(), user=operator) is operator


def test_k_permission_rejects_unassigned_employee(monkeypatch) -> None:
    monkeypatch.setattr(
        product_router,
        "resolve_current_user_permission_info",
        lambda _db, _user, request=None: SimpleNamespace(
            is_owner_full_access=False,
            permission_keys=[],
        ),
    )
    dependency = _require_k_permission("k.product_knowledge.update")

    with pytest.raises(HTTPException):
        dependency(
            request=SimpleNamespace(),
            db=object(),
            user=SimpleNamespace(role="operator"),
        )


def test_k_gate_configuration_errors_are_not_reported_as_forbidden() -> None:
    response = _gate_error(
        ModuleExecutionGateError(
            API_KEY_BINDING_MISSING_CODE,
            "Required API key binding is missing or not usable.",
            status_code=403,
            module_id="k.product_knowledge",
            org_id="org_test",
        )
    )

    assert response.status_code == 503
    assert response.detail["code"] == API_KEY_BINDING_MISSING_CODE
    assert "permission is valid" in response.detail["message"]


def test_workflow_gate_configuration_errors_are_not_reported_as_forbidden() -> None:
    response = _workflow_error(
        KWorkflowExecutionError(
            API_KEY_BINDING_MISSING_CODE,
            "Required API key binding is missing or not usable.",
            status_code=403,
            error_report={
                "code": API_KEY_BINDING_MISSING_CODE,
                "message": "Required API key binding is missing or not usable.",
                "blocking_step": "serp_keyword_fetch",
                "must_stop": True,
            },
        )
    )

    assert response.status_code == 503
    assert response.detail["code"] == API_KEY_BINDING_MISSING_CODE
    assert response.detail["blocking_step"] == "serp_keyword_fetch"
    assert "permission is valid" in response.detail["message"]
