from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.models.user import User
from backend.app.modules.k_series.product_knowledge.router import (
    product_knowledge_workflow_start,
)
from backend.app.modules.k_series.product_knowledge.schemas import (
    ProductKnowledgeWorkflowStartRequest,
)
from backend.app.modules.k_series.product_knowledge.workflow_engine import (
    KWorkflowOrchestratorV2,
)


class _FakeDb:
    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


def test_workflow_start_endpoint_does_not_return_raw_500(monkeypatch) -> None:
    def raise_unexpected_error(self, **_kwargs):  # noqa: ANN001
        raise RuntimeError("simulated pending rollback")

    def no_partial_execution(self, **_kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        KWorkflowOrchestratorV2,
        "start_pipeline",
        raise_unexpected_error,
    )
    monkeypatch.setattr(
        KWorkflowOrchestratorV2,
        "latest_execution_for_product",
        no_partial_execution,
    )
    db = _FakeDb()
    request = SimpleNamespace(state=SimpleNamespace(org_id=None))

    with pytest.raises(HTTPException) as exc_info:
        product_knowledge_workflow_start(
            product_id=uuid4(),
            payload=ProductKnowledgeWorkflowStartRequest(target_market="US"),
            request=request,  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
            user=User(id=1, username="owner", password_hash="x", role="owner"),
        )

    assert db.rolled_back is True
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "K_WORKFLOW_START_UNAVAILABLE"
    assert exc_info.value.detail["raw_error_class"] == "RuntimeError"
