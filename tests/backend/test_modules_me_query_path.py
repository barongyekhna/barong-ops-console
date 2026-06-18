from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.api.deps import require_cached_control_plane_admin
from backend.app.services import permission_service
from backend.app.services.permission_resolution_cache import (
    get_permission_request_cache,
)


def test_modules_me_reuses_cached_control_plane_rbac_decision() -> None:
    user = SimpleNamespace(id=1001, role="owner")
    request = SimpleNamespace(
        state=SimpleNamespace(
            control_plane_rbac_decision=SimpleNamespace(
                allowed=True,
                module_id="C16",
                action="admin",
            )
        )
    )

    assert require_cached_control_plane_admin(request, user) is user


def test_modules_me_rejects_missing_cached_control_plane_decision() -> None:
    user = SimpleNamespace(id=1002, role="owner")
    request = SimpleNamespace(state=SimpleNamespace())

    with pytest.raises(HTTPException) as exc_info:
        require_cached_control_plane_admin(request, user)

    assert exc_info.value.status_code == 403


def test_modules_me_permission_info_uses_request_material_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"scopes": 0}

    class DummyResolutionCache:
        def __init__(self, *, request: object | None = None) -> None:
            self.request = request

        def list_user_permission_scopes(
            self,
            db: object,
            *,
            user_id: int,
            now: object,
        ) -> list[SimpleNamespace]:
            del db, now
            calls["scopes"] += 1
            assert user_id == 2001
            return [
                SimpleNamespace(
                    permission_key="jobs.read",
                    scope_type="global",
                    scope_key="*",
                    expires_at=None,
                )
            ]

    monkeypatch.setattr(
        permission_service,
        "PermissionResolutionCache",
        DummyResolutionCache,
    )
    request = SimpleNamespace(state=SimpleNamespace())
    user = SimpleNamespace(id=2001, role="viewer")

    first = permission_service.resolve_current_user_module_permission_info(
        object(),
        user,
        request=request,
    )
    second = permission_service.resolve_current_user_module_permission_info(
        object(),
        user,
        request=request,
    )

    cache = get_permission_request_cache(request)
    assert first is second
    assert first.permission_keys == ["jobs.read"]
    assert calls["scopes"] == 1
    assert cache is not None
    assert cache.request_material_hits == 1
