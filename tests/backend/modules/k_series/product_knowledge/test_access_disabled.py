import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from backend.app.modules.k_series.product_knowledge import access
from backend.app.modules.k_series.product_knowledge.errors import (
    KProductKnowledgeDisabledError,
)


def test_disabled_feature_flag_denies_access_without_current_user() -> None:
    assert not inspect.iscoroutinefunction(access.require_k_product_knowledge_access)

    with pytest.raises(HTTPException) as exc_info:
        access.require_k_product_knowledge_access(None, "read")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail["code"] == KProductKnowledgeDisabledError.code


def test_disabled_feature_flag_does_not_default_allow_owner_role() -> None:
    user = SimpleNamespace(role="owner")

    with pytest.raises(HTTPException) as exc_info:
        access.require_k_product_knowledge_access(user, "read")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail["message"] == (
        KProductKnowledgeDisabledError.default_message
    )


def test_access_module_does_not_import_core_permission_registry() -> None:
    source = inspect.getsource(access)

    assert "core.permissions" not in source
    assert "permission_service" not in source
    assert "BASE_PERMISSION_REGISTRY_SEED" not in source
