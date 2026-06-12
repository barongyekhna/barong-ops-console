import inspect

from fastapi import APIRouter

from backend.app.modules.k_series.product_knowledge import router as router_module
from backend.app.modules.k_series.product_knowledge.constants import API_PREFIX


def _has_route(suffix: str, method: str) -> bool:
    candidate_paths = {f"{API_PREFIX}{suffix}", suffix}
    return any(
        getattr(route, "path", None) in candidate_paths
        and method in (getattr(route, "methods", None) or set())
        for route in router_module.router.routes
    )


def test_router_module_imports_and_exposes_router_object() -> None:
    assert isinstance(router_module.router, APIRouter)
    assert router_module.router.prefix == API_PREFIX


def test_router_paths_cover_k06_contract_without_starting_app() -> None:
    expected_routes = {
        "/": {"GET", "POST"},
        "/{product_id}": {"GET", "PATCH"},
        "/{product_id}/archive": {"POST"},
        "/{product_id}/attributes": {"GET", "PATCH"},
        "/{product_id}/keywords": {"GET", "PATCH"},
        "/{product_id}/risk-terms": {"GET", "PATCH"},
    }

    for suffix, methods in expected_routes.items():
        for method in methods:
            assert _has_route(suffix, method)


def test_router_module_does_not_self_register() -> None:
    source = inspect.getsource(router_module)

    assert "include_router" not in source
