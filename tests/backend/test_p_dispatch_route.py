from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend.app.db.base import Base
from backend.app.models.user import User
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeWorkflowExecution,
)
from backend.app.modules.p_series import router as p_router
from backend.app.modules.p_series.upload import assemble
from backend.app.services.data_isolation import (
    OrgDataIsolationSession,
    OrgDataIsolationUserContext,
    org_data_isolation_context,
)


pytestmark = pytest.mark.unit


def _request(product_id) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/app/p/products/{product_id}/dispatch",
            "headers": [],
        }
    )


def _owner() -> User:
    return User(
        id=7,
        username="round6-owner",
        password_hash="x",
        role="owner",
        is_active=True,
    )


def test_dispatch_api_succeeds_when_canonical_gate_is_clear_and_workflow_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            KProductKnowledgeProduct.__table__,
            KProductKnowledgeMediaAsset.__table__,
            KProductKnowledgeWorkflowExecution.__table__,
        ],
    )
    db = sessionmaker(
        bind=engine,
        class_=OrgDataIsolationSession,
        expire_on_commit=False,
    )()
    product = KProductKnowledgeProduct(
        id=uuid4(),
        product_key="round6-dispatch-ready",
        product_name_en="Compact Outdoor Cooking Stove",
        product_status="exported",
        channel="woocommerce",
        marketing_copy_json={"status": "ready"},
        regular_price=Decimal("39.99"),
    )
    db.add(product)
    db.flush()
    db.add_all(
        [
            KProductKnowledgeMediaAsset(
                id=uuid4(),
                product_id=product.id,
                asset_type="image",
                asset_role="main",
                status="bound",
                review_status="approved",
            ),
            KProductKnowledgeWorkflowExecution(
                id=uuid4(),
                product_id=product.id,
                organization_name=product.organization_name,
                workspace_key=product.workspace_key,
                business_context=product.business_context,
                scope_mode=product.scope_mode,
                target_market="US",
                status="exported",
                current_step="export_payloads",
                trace_json=[],
                export_payloads_json={"status": "exported"},
                execution_gate_logs_json=[],
            ),
        ]
    )
    db.commit()

    monkeypatch.setattr(assemble, "_evidence_gate_blockers", lambda product: [])
    monkeypatch.setattr(assemble, "category_is_bound", lambda product: True)
    monkeypatch.setattr(assemble, "audit_gate_blockers", lambda db, product: [])
    monkeypatch.setattr(assemble, "_non_webp_image_blockers", lambda db, product: [])

    dispatch_calls: list[dict[str, object]] = []

    def fake_create_dispatch_job(
        db,
        *,
        product_id,
        channel: str,
        public_base: str,
    ):
        dispatch_calls.append(
            {
                "db": db,
                "product_id": product_id,
                "channel": channel,
                "public_base": public_base,
            }
        )
        return SimpleNamespace(job_id="round6-job", status="queued")

    monkeypatch.setattr(p_router, "create_dispatch_job", fake_create_dispatch_job)
    user = _owner()
    request = _request(product.id)
    strict_context = OrgDataIsolationUserContext(
        org_id="org_00000000000000000000000000000001",
        user_id=str(user.id),
        role="owner",
        source="round6_dispatch_regression",
        strict=True,
    )

    with org_data_isolation_context(strict_context):
        response = p_router.p_dispatch(
            product.id,
            request,
            channel="woocommerce",
            db=db,
            user=user,
        )

    assert response.model_dump() == {
        "job_id": "round6-job",
        "status": "queued",
        "dispatched": False,
    }
    assert dispatch_calls == [
        {
            "db": db,
            "product_id": product.id,
            "channel": "woocommerce",
            "public_base": "https://ops.barongyekhna.com",
        }
    ]

    db.close()
    engine.dispose()


class _RouteDB:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.rollback_calls = 0

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollback_calls += 1


def test_dispatch_create_failure_is_logged_and_not_remapped_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    product_id = uuid4()
    db = _RouteDB()
    original = RuntimeError("queue insert failed")
    monkeypatch.setattr(p_router, "_load_product", lambda db, product_id: object())
    monkeypatch.setattr(p_router, "gate_blockers", lambda db, product: [])

    def fail_create(*args, **kwargs):
        del args, kwargs
        raise original

    monkeypatch.setattr(p_router, "create_dispatch_job", fail_create)

    with caplog.at_level("ERROR", logger=p_router.__name__):
        with pytest.raises(RuntimeError) as caught:
            p_router.p_dispatch(
                product_id,
                _request(product_id),
                db=db,
                user=_owner(),
            )

    assert caught.value is original
    assert db.rollback_calls == 1
    record = next(
        record
        for record in caplog.records
        if record.getMessage().startswith("P dispatch job creation failed")
    )
    assert record.exc_info is not None
    assert record.exc_info[1] is original


def test_dispatch_commit_failure_is_logged_and_not_remapped_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    product_id = uuid4()
    original = RuntimeError("commit failed")
    db = _RouteDB(commit_error=original)
    monkeypatch.setattr(p_router, "_load_product", lambda db, product_id: object())
    monkeypatch.setattr(p_router, "gate_blockers", lambda db, product: [])
    monkeypatch.setattr(
        p_router,
        "create_dispatch_job",
        lambda *args, **kwargs: SimpleNamespace(
            job_id="round6-commit-failure",
            status="queued",
        ),
    )

    with caplog.at_level("ERROR", logger=p_router.__name__):
        with pytest.raises(RuntimeError) as caught:
            p_router.p_dispatch(
                product_id,
                _request(product_id),
                db=db,
                user=_owner(),
            )

    assert caught.value is original
    assert db.rollback_calls == 1
    record = next(
        record
        for record in caplog.records
        if record.getMessage().startswith("P dispatch commit failed")
    )
    assert record.exc_info is not None
    assert record.exc_info[1] is original
