from __future__ import annotations

from datetime import UTC, datetime
import time

import pytest

from backend.app.schemas.module_control import (
    ModuleControlCenterResponse,
    ModuleControlOrgGroup,
    ModuleControlStateRead,
)
from backend.app.services import module_control_cache_service as cache
from tests.fixtures.organization_fixtures import (
    DEFAULT_TEST_ORG_DB_ID,
    TARGET_TEST_ORG_NAME,
)


def _module_state(*, enabled: bool = True) -> ModuleControlStateRead:
    return ModuleControlStateRead(
        org_id=DEFAULT_TEST_ORG_DB_ID,
        module_id="core.dashboard",
        display_name="Dashboard",
        category="core",
        enabled=enabled,
        runtime_status="active" if enabled else "disabled",
        runtime_error_code=None,
        runtime_error_message=None,
        last_error_at=None,
        updated_at=datetime.now(UTC),
    )


def test_module_control_cache_miss_returns_partial_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.stop_module_control_cache_worker()
    cache.reset_module_control_center_cache_for_tests()

    def slow_refresh():
        time.sleep(0.05)
        raise RuntimeError("slow backend aggregation")

    monkeypatch.setattr(cache, "_refresh_snapshot", slow_refresh)
    cache.start_module_control_cache_worker()

    started = time.perf_counter()
    response = cache.get_module_control_center_cached(max_wait_seconds=0.001)
    elapsed = time.perf_counter() - started

    assert response.cache_status == "partial"
    assert response.organization_count == 0
    assert elapsed < 0.03

    cache.stop_module_control_cache_worker()
    cache.reset_module_control_center_cache_for_tests()


def test_module_control_cache_applies_state_update_to_snapshot() -> None:
    cache.stop_module_control_cache_worker()
    cache.reset_module_control_center_cache_for_tests()
    response = ModuleControlCenterResponse(
        organizations=[
            ModuleControlOrgGroup(
                org_id=DEFAULT_TEST_ORG_DB_ID,
                org_name=TARGET_TEST_ORG_NAME,
                modules=[_module_state(enabled=True)],
            )
        ],
        organization_count=1,
        module_count=1,
        auto_registered_count=0,
    )
    snapshot = cache._snapshot_from_response(  # noqa: SLF001
        response,
        api_key_binding_summary={"active_binding_count": 0},
    )
    with cache._condition:  # noqa: SLF001
        cache._snapshot = snapshot  # noqa: SLF001

    assert cache.apply_module_control_state_to_cache(_module_state(enabled=False))

    cached = cache.get_module_control_center_cached()
    module = cached.organizations[0].modules[0]
    assert cached.cache_status == "fresh"
    assert module.enabled is False
    assert module.runtime_status == "disabled"

    cache.stop_module_control_cache_worker()
    cache.reset_module_control_center_cache_for_tests()
