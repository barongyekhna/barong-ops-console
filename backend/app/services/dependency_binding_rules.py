from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from ..core.dependency_bindings import (
    MODULE_CAPABILITY_BINDINGS_V1,
    MODULE_SERVICE_BINDINGS_V1,
    SERVICE_CAPABILITY_MAPPINGS_V1,
)
from ..schemas.dependency_binding import (
    DependencyBindingAuditEntry,
    DependencyBindingAuditResponse,
    DependencyBindingRuleSetResponse,
    DependencyBindingStatus,
    DependencyBindingValidationIssue,
    DependencyBindingValidationResult,
    DependencyCapability,
    DependencyGraphCapabilityNode,
    DependencyGraphEdge,
    DependencyGraphEdgeStatus,
    DependencyGraphModuleNode,
    DependencyGraphResponse,
    DependencyGraphServiceNode,
    DependencyGraphSnapshot,
    ModuleCapabilityBinding,
    ModuleServiceBinding,
    ServiceCapabilityMapping,
)
from ..schemas.external_dependency import ExternalService
from .external_dependency_governance import (
    EXTERNAL_SERVICE_ID_PATTERN,
    SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS,
    validate_external_service_registry,
)
from .module_adapter_registry import list_adapter_contracts
from .module_registry import MODULE_KEY_PATTERN, list_module_manifests


ALLOWED_DEPENDENCY_CAPABILITIES = frozenset(get_args(DependencyCapability))
ALLOWED_DEPENDENCY_BINDING_STATUSES = frozenset(
    get_args(DependencyBindingStatus)
)


def _module_service_binding_from_raw(
    raw: ModuleServiceBinding | Mapping[str, Any],
) -> ModuleServiceBinding:
    if isinstance(raw, ModuleServiceBinding):
        return raw
    return ModuleServiceBinding.model_validate(raw)


def _module_capability_binding_from_raw(
    raw: ModuleCapabilityBinding | Mapping[str, Any],
) -> ModuleCapabilityBinding:
    if isinstance(raw, ModuleCapabilityBinding):
        return raw
    return ModuleCapabilityBinding.model_validate(raw)


def _service_capability_mapping_from_raw(
    raw: ServiceCapabilityMapping | Mapping[str, Any],
) -> ServiceCapabilityMapping:
    if isinstance(raw, ServiceCapabilityMapping):
        return raw
    return ServiceCapabilityMapping.model_validate(raw)


def _iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_string_values(item)


def _contains_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered for marker in SENSITIVE_EXTERNAL_DEPENDENCY_MARKERS
    )


def _validate_safe_values(rule_key: str, payload: Mapping[str, Any]) -> None:
    for value in _iter_string_values(payload):
        if _contains_sensitive_marker(value):
            raise ValueError(f"{rule_key} contains sensitive runtime data.")


def _validate_module_key(module_key: str) -> None:
    if not MODULE_KEY_PATTERN.fullmatch(module_key):
        raise ValueError("Dependency binding module_key is invalid.")


def _validate_service_id(service_id: str) -> None:
    if not EXTERNAL_SERVICE_ID_PATTERN.fullmatch(service_id):
        raise ValueError("Dependency binding service_id is invalid.")
    if _contains_sensitive_marker(service_id):
        raise ValueError("Dependency binding service_id contains a blocked marker.")


def _validate_capability_list(rule_key: str, capabilities: Sequence[str]) -> None:
    if len(capabilities) != len(set(capabilities)):
        raise ValueError(f"{rule_key} has duplicate capabilities.")
    for capability in capabilities:
        if capability not in ALLOWED_DEPENDENCY_CAPABILITIES:
            raise ValueError(f"{rule_key} has invalid capability: {capability}")


def _validate_binding_status(rule_key: str, binding_status: str) -> None:
    if binding_status not in ALLOWED_DEPENDENCY_BINDING_STATUSES:
        raise ValueError(f"{rule_key} has invalid binding_status.")


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def list_module_service_bindings(
    raw_bindings: Sequence[ModuleServiceBinding | Mapping[str, Any]] | None = None,
) -> list[ModuleServiceBinding]:
    source = (
        raw_bindings
        if raw_bindings is not None
        else MODULE_SERVICE_BINDINGS_V1
    )
    bindings = [_module_service_binding_from_raw(raw) for raw in source]
    seen_pairs: set[tuple[str, str]] = set()

    for binding in bindings:
        _validate_module_key(binding.module_key)
        _validate_service_id(binding.service_id)
        _validate_binding_status(
            f"{binding.module_key}.{binding.service_id}",
            binding.binding_status,
        )
        _validate_capability_list(
            f"{binding.module_key}.{binding.service_id}",
            binding.allowed_capabilities,
        )
        pair = (binding.module_key, binding.service_id)
        if pair in seen_pairs:
            raise ValueError(
                f"Duplicate module service binding: {binding.module_key} -> "
                f"{binding.service_id}"
            )
        seen_pairs.add(pair)
        _validate_safe_values(
            f"{binding.module_key}.{binding.service_id}",
            binding.model_dump(mode="json"),
        )

    return bindings


def list_module_capability_bindings(
    raw_bindings: Sequence[ModuleCapabilityBinding | Mapping[str, Any]] | None = None,
) -> list[ModuleCapabilityBinding]:
    source = (
        raw_bindings
        if raw_bindings is not None
        else MODULE_CAPABILITY_BINDINGS_V1
    )
    bindings = [_module_capability_binding_from_raw(raw) for raw in source]
    seen_modules: set[str] = set()

    for binding in bindings:
        _validate_module_key(binding.module_key)
        _validate_binding_status(binding.module_key, binding.binding_status)
        _validate_capability_list(binding.module_key, binding.allowed_capabilities)
        if binding.module_key in seen_modules:
            raise ValueError(
                f"Duplicate module capability binding: {binding.module_key}"
            )
        seen_modules.add(binding.module_key)
        _validate_safe_values(
            binding.module_key,
            binding.model_dump(mode="json"),
        )

    return bindings


def list_service_capability_mappings(
    raw_mappings: Sequence[ServiceCapabilityMapping | Mapping[str, Any]] | None = None,
) -> list[ServiceCapabilityMapping]:
    source = (
        raw_mappings
        if raw_mappings is not None
        else SERVICE_CAPABILITY_MAPPINGS_V1
    )
    mappings = [_service_capability_mapping_from_raw(raw) for raw in source]
    seen_services: set[str] = set()

    for mapping in mappings:
        _validate_service_id(mapping.service_id)
        _validate_binding_status(mapping.service_id, mapping.binding_status)
        _validate_capability_list(mapping.service_id, mapping.capabilities)
        if mapping.service_id in seen_services:
            raise ValueError(
                f"Duplicate service capability mapping: {mapping.service_id}"
            )
        seen_services.add(mapping.service_id)
        _validate_safe_values(
            mapping.service_id,
            mapping.model_dump(mode="json"),
        )

    return mappings


def list_dependency_binding_rules(
    *,
    raw_module_service_bindings: Sequence[ModuleServiceBinding | Mapping[str, Any]]
    | None = None,
    raw_module_capability_bindings: Sequence[
        ModuleCapabilityBinding | Mapping[str, Any]
    ]
    | None = None,
    raw_service_capability_mappings: Sequence[
        ServiceCapabilityMapping | Mapping[str, Any]
    ]
    | None = None,
) -> DependencyBindingRuleSetResponse:
    module_service_bindings = list_module_service_bindings(
        raw_module_service_bindings
    )
    module_capability_bindings = list_module_capability_bindings(
        raw_module_capability_bindings
    )
    service_capability_mappings = list_service_capability_mappings(
        raw_service_capability_mappings
    )
    return DependencyBindingRuleSetResponse(
        module_service_bindings=module_service_bindings,
        module_capability_bindings=module_capability_bindings,
        service_capability_mappings=service_capability_mappings,
        count=(
            len(module_service_bindings)
            + len(module_capability_bindings)
            + len(service_capability_mappings)
        ),
    )


def _issue(
    *,
    code: str,
    message: str,
    module_key: str | None = None,
    service_id: str | None = None,
    capability: DependencyCapability | None = None,
    severity: str = "error",
) -> DependencyBindingValidationIssue:
    return DependencyBindingValidationIssue(
        severity=severity,
        code=code,
        message=message,
        module_key=module_key,
        service_id=service_id,
        capability=capability,
    )


def _declared_service_ids_by_module() -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    manifest_declarations = {
        manifest.module_key: set(manifest.external_dependencies)
        for manifest in list_module_manifests()
    }
    adapter_declarations: dict[str, set[str]] = {}
    for adapter in list_adapter_contracts():
        adapter_declarations.setdefault(adapter.module_key, set()).update(
            dependency.dependency_key
            for dependency in adapter.dependency_declarations
        )

    declared: dict[str, set[str]] = {
        module_key: set(service_ids)
        for module_key, service_ids in manifest_declarations.items()
    }
    for module_key, service_ids in adapter_declarations.items():
        declared.setdefault(module_key, set()).update(service_ids)
    return declared, manifest_declarations, adapter_declarations


def _dependency_graph_edge_count(bindings: Sequence[ModuleServiceBinding]) -> int:
    return sum(
        len(binding.allowed_capabilities)
        for binding in bindings
        if binding.binding_status != "disabled"
    )


def validate_dependency_binding_rules(
    *,
    raw_module_service_bindings: Sequence[ModuleServiceBinding | Mapping[str, Any]]
    | None = None,
    raw_module_capability_bindings: Sequence[
        ModuleCapabilityBinding | Mapping[str, Any]
    ]
    | None = None,
    raw_service_capability_mappings: Sequence[
        ServiceCapabilityMapping | Mapping[str, Any]
    ]
    | None = None,
    raw_services: Sequence[ExternalService | Mapping[str, Any]] | None = None,
) -> DependencyBindingValidationResult:
    module_service_bindings = list_module_service_bindings(
        raw_module_service_bindings
    )
    module_capability_bindings = list_module_capability_bindings(
        raw_module_capability_bindings
    )
    service_capability_mappings = list_service_capability_mappings(
        raw_service_capability_mappings
    )
    services = validate_external_service_registry(raw_services)
    service_lookup = {service.service_id: service for service in services}
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    declared, manifest_declarations, adapter_declarations = (
        _declared_service_ids_by_module()
    )
    binding_lookup = {
        (binding.module_key, binding.service_id): binding
        for binding in module_service_bindings
    }
    module_policy_lookup = {
        binding.module_key: binding for binding in module_capability_bindings
    }
    service_policy_lookup = {
        mapping.service_id: mapping for mapping in service_capability_mappings
    }
    issues: list[DependencyBindingValidationIssue] = []

    for module_key, service_ids in declared.items():
        for service_id in sorted(service_ids):
            if (module_key, service_id) not in binding_lookup:
                issues.append(
                    _issue(
                        code="c14e_module_external_dependency_unbound",
                        message=(
                            "Module external dependency must have an explicit "
                            "module-service binding."
                        ),
                        module_key=module_key,
                        service_id=service_id,
                    )
                )

    for module_key, service_ids in adapter_declarations.items():
        manifest_service_ids = manifest_declarations.get(module_key, set())
        for service_id in sorted(service_ids - manifest_service_ids):
            issues.append(
                _issue(
                    code="c14e_adapter_dependency_not_declared_by_module",
                    message=(
                        "Adapter dependency must be declared by the owning "
                        "module manifest."
                    ),
                    module_key=module_key,
                    service_id=service_id,
                )
            )

    modules_requiring_capability_policy = set(declared) | {
        binding.module_key for binding in module_service_bindings
    }
    for module_key in sorted(modules_requiring_capability_policy):
        if declared.get(module_key) and module_key not in module_policy_lookup:
            issues.append(
                _issue(
                    code="c14e_module_capability_policy_missing",
                    message=(
                        "Module with external dependency must declare allowed "
                        "capabilities explicitly."
                    ),
                    module_key=module_key,
                )
            )

    for binding in module_service_bindings:
        module_policy = module_policy_lookup.get(binding.module_key)
        service_policy = service_policy_lookup.get(binding.service_id)
        declared_for_module = declared.get(binding.module_key, set())
        service = service_lookup.get(binding.service_id)

        if binding.module_key not in module_keys:
            issues.append(
                _issue(
                    code="c14e_module_not_registered",
                    message="Module-service binding references an unknown module.",
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )
        if binding.service_id not in declared_for_module:
            issues.append(
                _issue(
                    code="c14e_module_service_not_declared",
                    message=(
                        "Module-service binding cannot reference a service that "
                        "the module did not declare."
                    ),
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )
        if module_policy is None:
            issues.append(
                _issue(
                    code="c14e_module_capability_policy_missing",
                    message="Module capability binding is required for service use.",
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )
        if service_policy is None:
            issues.append(
                _issue(
                    code="c14e_service_capability_mapping_missing",
                    message="Service capability mapping is required for service use.",
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )

        if (
            binding.binding_status == "disabled"
            and binding.allowed_capabilities
        ):
            issues.append(
                _issue(
                    code="c14e_disabled_binding_grants_capability",
                    message="Disabled module-service binding cannot grant capability.",
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )
        if (
            binding.binding_status in {"active", "restricted"}
            and not binding.allowed_capabilities
        ):
            issues.append(
                _issue(
                    code="c14e_enabled_binding_has_no_capability",
                    message=(
                        "Active or restricted module-service binding must name "
                        "at least one capability."
                    ),
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )
        if binding.binding_status in {"active", "restricted"} and service is None:
            issues.append(
                _issue(
                    code="c14e_enabled_binding_service_unregistered",
                    message=(
                        "Active or restricted module-service binding requires a "
                        "registered external service."
                    ),
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )
        if (
            binding.binding_status == "active"
            and service is not None
            and service.status != "active"
        ):
            issues.append(
                _issue(
                    code="c14e_active_binding_service_not_active",
                    message="Active binding requires service status active.",
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )
        if (
            binding.binding_status == "restricted"
            and service is not None
            and service.status in {"suspended", "quarantined"}
        ):
            issues.append(
                _issue(
                    code="c14e_restricted_binding_service_blocked",
                    message=(
                        "Restricted binding cannot target suspended or "
                        "quarantined service."
                    ),
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                )
            )

        for capability in binding.allowed_capabilities:
            if (
                module_policy is not None
                and capability not in module_policy.allowed_capabilities
            ):
                issues.append(
                    _issue(
                        code="c14e_capability_not_allowed_by_module",
                        message=(
                            "Requested capability is not in the module allowed "
                            "capability set."
                        ),
                        module_key=binding.module_key,
                        service_id=binding.service_id,
                        capability=capability,
                    )
                )
            if (
                service_policy is not None
                and capability not in service_policy.capabilities
            ):
                issues.append(
                    _issue(
                        code="c14e_capability_not_mapped_to_service",
                        message=(
                            "Requested capability is not mapped to the external "
                            "service."
                        ),
                        module_key=binding.module_key,
                        service_id=binding.service_id,
                        capability=capability,
                    )
                )

    for module_policy in module_capability_bindings:
        if module_policy.module_key not in module_keys:
            issues.append(
                _issue(
                    code="c14e_module_capability_unknown_module",
                    message="Module capability binding references an unknown module.",
                    module_key=module_policy.module_key,
                )
            )
        if (
            module_policy.binding_status == "disabled"
            and module_policy.allowed_capabilities
        ):
            issues.append(
                _issue(
                    code="c14e_disabled_module_policy_grants_capability",
                    message="Disabled module capability policy cannot grant capability.",
                    module_key=module_policy.module_key,
                )
            )

    for service_policy in service_capability_mappings:
        service = service_lookup.get(service_policy.service_id)
        if (
            service_policy.binding_status == "disabled"
            and service_policy.capabilities
        ):
            issues.append(
                _issue(
                    code="c14e_disabled_service_mapping_grants_capability",
                    message=(
                        "Disabled service capability mapping cannot grant "
                        "capability."
                    ),
                    service_id=service_policy.service_id,
                )
            )
        if (
            service_policy.binding_status in {"active", "restricted"}
            and service is None
        ):
            issues.append(
                _issue(
                    code="c14e_enabled_service_mapping_unregistered",
                    message=(
                        "Active or restricted service capability mapping "
                        "requires a registered service."
                    ),
                    service_id=service_policy.service_id,
                )
            )
        if (
            service_policy.binding_status in {"active", "restricted"}
            and not service_policy.capabilities
        ):
            issues.append(
                _issue(
                    code="c14e_enabled_service_mapping_has_no_capability",
                    message=(
                        "Active or restricted service mapping must name at "
                        "least one capability."
                    ),
                    service_id=service_policy.service_id,
                )
            )

    return DependencyBindingValidationResult(
        valid=not any(issue.severity == "error" for issue in issues),
        issues=issues,
        module_service_binding_count=len(module_service_bindings),
        module_capability_binding_count=len(module_capability_bindings),
        service_capability_mapping_count=len(service_capability_mappings),
        graph_edge_count=_dependency_graph_edge_count(module_service_bindings),
    )


def _edge_reasons(
    *,
    binding: ModuleServiceBinding,
    module_policy: ModuleCapabilityBinding | None,
    service_policy: ServiceCapabilityMapping | None,
    service: ExternalService | None,
    capability: DependencyCapability,
) -> tuple[DependencyGraphEdgeStatus, list[str]]:
    reasons: list[str] = []
    if module_policy is None:
        reasons.append("c14e_module_capability_policy_missing")
    elif capability not in module_policy.allowed_capabilities:
        reasons.append("c14e_capability_not_allowed_by_module")
    if service_policy is None:
        reasons.append("c14e_service_capability_mapping_missing")
    elif capability not in service_policy.capabilities:
        reasons.append("c14e_capability_not_mapped_to_service")
    if service is None:
        reasons.append("c14e_service_not_registered")
    elif binding.binding_status == "active" and service.status != "active":
        reasons.append("c14e_active_binding_service_not_active")
    elif binding.binding_status == "restricted" and service.status in {
        "suspended",
        "quarantined",
    }:
        reasons.append("c14e_restricted_binding_service_blocked")

    if reasons:
        return "blocked", reasons
    if binding.binding_status == "restricted":
        return "restricted", ["c14e_binding_restricted"]
    return "valid", ["c14e_binding_validated"]


def build_dependency_graph(
    *,
    raw_module_service_bindings: Sequence[ModuleServiceBinding | Mapping[str, Any]]
    | None = None,
    raw_module_capability_bindings: Sequence[
        ModuleCapabilityBinding | Mapping[str, Any]
    ]
    | None = None,
    raw_service_capability_mappings: Sequence[
        ServiceCapabilityMapping | Mapping[str, Any]
    ]
    | None = None,
    raw_services: Sequence[ExternalService | Mapping[str, Any]] | None = None,
) -> DependencyGraphSnapshot:
    module_service_bindings = list_module_service_bindings(
        raw_module_service_bindings
    )
    module_capability_bindings = list_module_capability_bindings(
        raw_module_capability_bindings
    )
    service_capability_mappings = list_service_capability_mappings(
        raw_service_capability_mappings
    )
    services = validate_external_service_registry(raw_services)
    service_lookup = {service.service_id: service for service in services}
    declared, _, _ = _declared_service_ids_by_module()
    validation = validate_dependency_binding_rules(
        raw_module_service_bindings=module_service_bindings,
        raw_module_capability_bindings=module_capability_bindings,
        raw_service_capability_mappings=service_capability_mappings,
        raw_services=services,
    )
    binding_lookup = {
        (binding.module_key, binding.service_id): binding
        for binding in module_service_bindings
    }
    module_policy_lookup = {
        binding.module_key: binding for binding in module_capability_bindings
    }
    service_policy_lookup = {
        mapping.service_id: mapping for mapping in service_capability_mappings
    }

    module_ids = sorted(
        set(declared)
        | {binding.module_key for binding in module_service_bindings}
        | {binding.module_key for binding in module_capability_bindings}
    )
    modules = [
        DependencyGraphModuleNode(
            module_key=module_key,
            declared_service_ids=sorted(declared.get(module_key, set())),
            allowed_capabilities=(
                module_policy_lookup[module_key].allowed_capabilities
                if module_key in module_policy_lookup
                else []
            ),
            binding_status=(
                module_policy_lookup[module_key].binding_status
                if module_key in module_policy_lookup
                else "disabled"
            ),
            explicit_binding_present=all(
                (module_key, service_id) in binding_lookup
                for service_id in declared.get(module_key, set())
            ),
        )
        for module_key in module_ids
        if declared.get(module_key)
        or module_key in module_policy_lookup
        or any(
            binding.module_key == module_key for binding in module_service_bindings
        )
    ]

    service_ids = sorted(
        {binding.service_id for binding in module_service_bindings}
        | {mapping.service_id for mapping in service_capability_mappings}
    )
    services_nodes = [
        DependencyGraphServiceNode(
            service_id=service_id,
            service_registered=service_id in service_lookup,
            service_status=(
                service_lookup[service_id].status
                if service_id in service_lookup
                else "missing"
            ),
            trust_level=(
                service_lookup[service_id].trust_level
                if service_id in service_lookup
                else "untrusted"
            ),
            capabilities=(
                service_policy_lookup[service_id].capabilities
                if service_id in service_policy_lookup
                else []
            ),
            binding_status=(
                service_policy_lookup[service_id].binding_status
                if service_id in service_policy_lookup
                else "disabled"
            ),
        )
        for service_id in service_ids
    ]

    capabilities = [
        DependencyGraphCapabilityNode(
            capability=capability,
            module_count=sum(
                1
                for binding in module_capability_bindings
                if binding.binding_status != "disabled"
                and capability in binding.allowed_capabilities
            ),
            service_count=sum(
                1
                for mapping in service_capability_mappings
                if mapping.binding_status != "disabled"
                and capability in mapping.capabilities
            ),
        )
        for capability in sorted(ALLOWED_DEPENDENCY_CAPABILITIES)
    ]

    edges: list[DependencyGraphEdge] = []
    for binding in module_service_bindings:
        if binding.binding_status == "disabled":
            continue
        module_policy = module_policy_lookup.get(binding.module_key)
        service_policy = service_policy_lookup.get(binding.service_id)
        service = service_lookup.get(binding.service_id)
        for capability in binding.allowed_capabilities:
            validation_status, reasons = _edge_reasons(
                binding=binding,
                module_policy=module_policy,
                service_policy=service_policy,
                service=service,
                capability=capability,
            )
            edge_payload = {
                "module_key": binding.module_key,
                "capability": capability,
                "service_id": binding.service_id,
            }
            edges.append(
                DependencyGraphEdge(
                    edge_id=_stable_id("c14e_edge", edge_payload),
                    module_key=binding.module_key,
                    capability=capability,
                    service_id=binding.service_id,
                    binding_status=binding.binding_status,
                    validation_status=validation_status,
                    reasons=reasons,
                    audit_ref=_stable_id("c14e_audit", edge_payload),
                )
            )

    return DependencyGraphSnapshot(
        modules=modules,
        capabilities=capabilities,
        services=services_nodes,
        edges=edges,
        validation=validation,
    )


def build_dependency_graph_response() -> DependencyGraphResponse:
    return DependencyGraphResponse(graph=build_dependency_graph())


def _audit_reason(reasons: Sequence[str]) -> str:
    if not reasons:
        return "c14e_binding_validated"
    return "; ".join(reasons)[:500]


def list_dependency_binding_audit(
    *,
    raw_module_service_bindings: Sequence[ModuleServiceBinding | Mapping[str, Any]]
    | None = None,
    raw_module_capability_bindings: Sequence[
        ModuleCapabilityBinding | Mapping[str, Any]
    ]
    | None = None,
    raw_service_capability_mappings: Sequence[
        ServiceCapabilityMapping | Mapping[str, Any]
    ]
    | None = None,
    raw_services: Sequence[ExternalService | Mapping[str, Any]] | None = None,
) -> list[DependencyBindingAuditEntry]:
    module_service_bindings = list_module_service_bindings(
        raw_module_service_bindings
    )
    graph = build_dependency_graph(
        raw_module_service_bindings=module_service_bindings,
        raw_module_capability_bindings=raw_module_capability_bindings,
        raw_service_capability_mappings=raw_service_capability_mappings,
        raw_services=raw_services,
    )
    edge_lookup = {
        (edge.module_key, edge.service_id, edge.capability): edge
        for edge in graph.edges
    }
    audit_entries: list[DependencyBindingAuditEntry] = []

    for binding in module_service_bindings:
        if binding.binding_status == "disabled":
            audit_entries.append(
                DependencyBindingAuditEntry(
                    audit_id=_stable_id(
                        "c14e_audit",
                        {
                            "module_key": binding.module_key,
                            "service_id": binding.service_id,
                            "capability": None,
                        },
                    ),
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                    binding_status=binding.binding_status,
                    decision="block",
                    reason="c14e_module_service_binding_disabled",
                )
            )
            continue
        if not binding.allowed_capabilities:
            audit_entries.append(
                DependencyBindingAuditEntry(
                    audit_id=_stable_id(
                        "c14e_audit",
                        {
                            "module_key": binding.module_key,
                            "service_id": binding.service_id,
                            "capability": None,
                        },
                    ),
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                    binding_status=binding.binding_status,
                    decision="block",
                    reason="c14e_no_capability_bound",
                )
            )
            continue
        for capability in binding.allowed_capabilities:
            edge = edge_lookup.get(
                (binding.module_key, binding.service_id, capability)
            )
            if edge is None or edge.validation_status == "blocked":
                decision = "block"
                reason = (
                    _audit_reason(edge.reasons)
                    if edge is not None
                    else "c14e_dependency_graph_edge_missing"
                )
            elif edge.validation_status == "restricted":
                decision = "restrict"
                reason = _audit_reason(edge.reasons)
            else:
                decision = "allow"
                reason = _audit_reason(edge.reasons)
            audit_entries.append(
                DependencyBindingAuditEntry(
                    audit_id=_stable_id(
                        "c14e_audit",
                        {
                            "module_key": binding.module_key,
                            "service_id": binding.service_id,
                            "capability": capability,
                        },
                    ),
                    module_key=binding.module_key,
                    service_id=binding.service_id,
                    capability=capability,
                    binding_status=binding.binding_status,
                    decision=decision,
                    reason=reason,
                )
            )

    return audit_entries


def build_dependency_binding_audit_response() -> DependencyBindingAuditResponse:
    entries = list_dependency_binding_audit()
    return DependencyBindingAuditResponse(items=entries, count=len(entries))


__all__ = [
    "ALLOWED_DEPENDENCY_BINDING_STATUSES",
    "ALLOWED_DEPENDENCY_CAPABILITIES",
    "build_dependency_binding_audit_response",
    "build_dependency_graph",
    "build_dependency_graph_response",
    "list_dependency_binding_audit",
    "list_dependency_binding_rules",
    "list_module_capability_bindings",
    "list_module_service_bindings",
    "list_service_capability_mappings",
    "validate_dependency_binding_rules",
]
