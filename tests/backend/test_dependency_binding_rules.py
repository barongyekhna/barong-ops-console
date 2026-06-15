from __future__ import annotations

import re
from typing import Any

import pytest

from backend.app.main import app
from backend.app.services.dependency_binding_rules import (
    build_dependency_graph,
    list_dependency_binding_audit,
    list_dependency_binding_rules,
    list_module_service_bindings,
    validate_dependency_binding_rules,
)


def c14e_registered_service(**updates: Any) -> dict[str, Any]:
    service = {
        "service_id": "n8n",
        "service_type": "automation",
        "status": "active",
        "trust_level": "high",
        "metadata": {
            "registration_source": "c14e_contract_test",
            "owner_module": "integration.n8n_test_bridge",
        },
    }
    service.update(updates)
    return service


def c14e_module_service_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "module_key": "integration.n8n_test_bridge",
        "service_id": "n8n",
        "binding_status": "restricted",
        "allowed_capabilities": ["serp"],
        "reason": "Restricted C14E capability grant for contract inspection.",
    }
    binding.update(updates)
    return binding


def c14e_module_capability_binding(**updates: Any) -> dict[str, Any]:
    binding = {
        "module_key": "integration.n8n_test_bridge",
        "allowed_capabilities": ["serp"],
        "binding_status": "restricted",
        "reason": "Module may inspect serp capability binding only.",
    }
    binding.update(updates)
    return binding


def c14e_service_capability_mapping(**updates: Any) -> dict[str, Any]:
    mapping = {
        "service_id": "n8n",
        "capabilities": ["serp"],
        "binding_status": "restricted",
        "reason": "Service maps serp capability for contract inspection.",
    }
    mapping.update(updates)
    return mapping


def test_c14e_default_rules_explicitly_disable_n8n_capabilities() -> None:
    rules = list_dependency_binding_rules()
    validation = validate_dependency_binding_rules()
    graph = build_dependency_graph()
    audit = list_dependency_binding_audit()
    n8n_binding = next(
        binding
        for binding in rules.module_service_bindings
        if binding.module_key == "integration.n8n_test_bridge"
        and binding.service_id == "n8n"
    )

    assert n8n_binding.binding_status == "disabled"
    assert n8n_binding.allowed_capabilities == []
    assert validation.valid is True
    assert graph.validation.valid is True
    assert graph.edges == []
    assert any(
        node.service_id == "n8n"
        and node.service_registered is False
        and node.service_status == "missing"
        for node in graph.services
    )
    assert any(
        entry.module_key == "integration.n8n_test_bridge"
        and entry.service_id == "n8n"
        and entry.decision == "block"
        for entry in audit
    )


def test_c14e_dependency_graph_builds_restricted_explicit_edge() -> None:
    validation = validate_dependency_binding_rules(
        raw_module_service_bindings=[c14e_module_service_binding()],
        raw_module_capability_bindings=[c14e_module_capability_binding()],
        raw_service_capability_mappings=[c14e_service_capability_mapping()],
        raw_services=[c14e_registered_service()],
    )
    graph = build_dependency_graph(
        raw_module_service_bindings=[c14e_module_service_binding()],
        raw_module_capability_bindings=[c14e_module_capability_binding()],
        raw_service_capability_mappings=[c14e_service_capability_mapping()],
        raw_services=[c14e_registered_service()],
    )
    audit = list_dependency_binding_audit(
        raw_module_service_bindings=[c14e_module_service_binding()],
        raw_module_capability_bindings=[c14e_module_capability_binding()],
        raw_service_capability_mappings=[c14e_service_capability_mapping()],
        raw_services=[c14e_registered_service()],
    )

    assert validation.valid is True
    assert len(graph.edges) == 1
    assert graph.edges[0].module_key == "integration.n8n_test_bridge"
    assert graph.edges[0].capability == "serp"
    assert graph.edges[0].service_id == "n8n"
    assert graph.edges[0].validation_status == "restricted"
    assert audit[0].decision == "restrict"
    assert audit[0].no_runtime_execution is True
    assert audit[0].no_external_api_call is True


def test_c14e_validation_rejects_missing_explicit_module_service_binding() -> None:
    validation = validate_dependency_binding_rules(
        raw_module_service_bindings=[],
    )
    codes = {issue.code for issue in validation.issues}

    assert validation.valid is False
    assert "c14e_module_external_dependency_unbound" in codes


def test_c14e_validation_blocks_cross_module_binding_leakage() -> None:
    validation = validate_dependency_binding_rules(
        raw_module_service_bindings=[
            c14e_module_service_binding(module_key="business.products"),
        ],
        raw_module_capability_bindings=[
            c14e_module_capability_binding(module_key="business.products"),
        ],
        raw_service_capability_mappings=[c14e_service_capability_mapping()],
        raw_services=[c14e_registered_service()],
    )
    codes = {issue.code for issue in validation.issues}

    assert validation.valid is False
    assert "c14e_module_service_not_declared" in codes


def test_c14e_binding_rules_reject_sensitive_runtime_values() -> None:
    with pytest.raises(ValueError, match="sensitive runtime data"):
        list_module_service_bindings(
            [
                c14e_module_service_binding(
                    binding_status="disabled",
                    allowed_capabilities=[],
                    reason="contains token marker",
                )
            ]
        )


def test_c14e_router_exposes_only_read_contract_apis() -> None:
    routes = [
        (
            getattr(route, "path", ""),
            set(getattr(route, "methods", set()) or set()),
        )
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/api/control-plane/external-dependencies")
    ]

    assert ("/api/control-plane/external-dependencies/binding-rules", {"GET"}) in routes
    assert ("/api/control-plane/external-dependencies/dependency-graph", {"GET"}) in routes
    assert ("/api/control-plane/external-dependencies/binding-validation", {"GET"}) in routes
    assert ("/api/control-plane/external-dependencies/binding-audit", {"GET"}) in routes
    assert not any(
        methods & {"POST", "PUT", "PATCH", "DELETE"}
        for _, methods in routes
    )
    assert not any(
        re.search(r"/(?:actions?|execute|execution|run|sync)\b", path)
        for path, _ in routes
    )
