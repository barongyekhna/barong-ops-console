import re
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from sqlalchemy.orm import Session

from ..core.module_adapters import MODULE_ADAPTER_CONTRACTS_V1
from ..core.permissions import ALLOWED_SCOPE_TYPES, validate_permission_key
from ..models.user import User
from ..schemas.module import ModuleManifestV1
from ..schemas.module_adapter import (
    AdapterAccessState,
    AdapterDependencyName,
    AdapterStatus,
    AdapterSurface,
    ModuleAdapterAccessRead,
    ModuleAdapterContractV1,
)
from .module_registry import (
    MODULE_KEY_PATTERN,
    build_module_access_state,
    get_module_manifest,
    list_module_manifests,
)
from .permission_service import (
    CurrentUserPermissionInfo,
    resolve_current_user_permission_info,
)

ADAPTER_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)+$"
)
ADAPTER_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_ADAPTER_STATUSES = frozenset(get_args(AdapterStatus))
ALLOWED_ADAPTER_SURFACES = frozenset(get_args(AdapterSurface))
ALLOWED_ADAPTER_DEPENDENCIES = frozenset(get_args(AdapterDependencyName))
SAFE_ADAPTER_EXECUTION_TYPES = frozenset({"mock", "no_op"})
NON_EXECUTABLE_ADAPTER_STATUSES = {
    "draft",
    "adapter_pending",
    "disabled",
    "deprecated",
}
SENSITIVE_VALUE_MARKERS = (
    ".env",
    "authorization",
    "bearer ",
    "credential",
    "env",
    "http://",
    "https://",
    "password",
    "provider_url",
    "secret",
    "token",
    "url",
    "webhook",
    "://",
    "=",
)
LIVE_PROVIDER_DEPENDENCIES = {
    "n8n",
    "woocommerce",
    "minio",
    "filebrowser",
}


def _adapter_from_raw(
    raw: ModuleAdapterContractV1 | Mapping[str, Any],
) -> ModuleAdapterContractV1:
    if isinstance(raw, ModuleAdapterContractV1):
        return raw
    return ModuleAdapterContractV1.model_validate(raw)


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


def _validate_safe_values(adapter: ModuleAdapterContractV1) -> None:
    for value in _iter_string_values(adapter.model_dump()):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_VALUE_MARKERS):
            raise ValueError(
                f"{adapter.adapter_key} contains a sensitive runtime value."
            )


def _validate_adapter_key(adapter_key: str) -> None:
    if not ADAPTER_KEY_PATTERN.fullmatch(adapter_key):
        raise ValueError(
            "Adapter key must use lowercase snake_case or dot namespace."
        )


def _path_within_namespace(path: str, namespace: str) -> bool:
    if namespace == "no_api":
        return path == "no_api"
    normalized_namespace = namespace.rstrip("/")
    return path == normalized_namespace or path.startswith(
        f"{normalized_namespace}/"
    )


def _permission_keys_for_manifest(manifest: ModuleManifestV1) -> set[str]:
    return set(manifest.required_permissions) | {
        entry.permission_key for entry in manifest.permission_manifest
    }


def _required_permission_keys(adapter: ModuleAdapterContractV1) -> set[str]:
    permissions: set[str] = set()
    for page in adapter.pages:
        if page.required_permission:
            permissions.add(page.required_permission)
    for nav in adapter.nav_bindings:
        if nav.required_permission:
            permissions.add(nav.required_permission)
    for route in adapter.route_bindings:
        if route.required_permission:
            permissions.add(route.required_permission)
    for api in adapter.api_bindings:
        if api.required_permission:
            permissions.add(api.required_permission)
    for capability in adapter.capabilities:
        if capability.required_permission:
            permissions.add(capability.required_permission)
    for action in adapter.actions:
        permissions.add(action.required_permission)
    for contract in adapter.action_contracts:
        permissions.add(contract.required_permission)
    for binding in adapter.permission_bindings:
        permissions.add(binding.permission_key)
    return permissions


def _validate_module_binding(
    adapter: ModuleAdapterContractV1,
    manifest: ModuleManifestV1,
) -> None:
    if not MODULE_KEY_PATTERN.fullmatch(adapter.module_key):
        raise ValueError(f"{adapter.adapter_key} has invalid module_key.")

    for page in adapter.pages:
        if page.module_key != adapter.module_key:
            raise ValueError(f"{adapter.adapter_key} page module_key drift.")
        if page.route_namespace != manifest.route_namespace:
            raise ValueError(f"{adapter.adapter_key} page route namespace drift.")
        if not _path_within_namespace(page.route, manifest.route_namespace):
            raise ValueError(f"{adapter.adapter_key} page route escapes module.")

    for route in adapter.route_bindings:
        if route.module_key != adapter.module_key:
            raise ValueError(f"{adapter.adapter_key} route module_key drift.")
        if route.route_namespace != manifest.route_namespace:
            raise ValueError(f"{adapter.adapter_key} route namespace drift.")
        if not _path_within_namespace(route.path, manifest.route_namespace):
            raise ValueError(f"{adapter.adapter_key} route escapes module.")

    for api in adapter.api_bindings:
        if api.module_key != adapter.module_key:
            raise ValueError(f"{adapter.adapter_key} api module_key drift.")
        if api.no_api:
            if (
                api.api_namespace != "no_api"
                or api.path != "no_api"
                or api.method != "NO_API"
            ):
                raise ValueError(
                    f"{adapter.adapter_key} no_api binding is malformed."
                )
            continue
        if manifest.no_api:
            raise ValueError(
                f"{adapter.adapter_key} declares API for no_api module."
            )
        if api.api_namespace != manifest.api_namespace:
            raise ValueError(f"{adapter.adapter_key} api namespace drift.")
        if not _path_within_namespace(api.path, manifest.api_namespace):
            raise ValueError(f"{adapter.adapter_key} api escapes module.")

    for nav in adapter.nav_bindings:
        if nav.module_key != adapter.module_key:
            raise ValueError(f"{adapter.adapter_key} nav module_key drift.")
        if not _path_within_namespace(nav.route, manifest.route_namespace):
            raise ValueError(f"{adapter.adapter_key} nav route escapes module.")
        if nav.denied_behavior != manifest.denied_behavior:
            raise ValueError(
                f"{adapter.adapter_key} nav denied behavior bypasses C07."
            )


def _validate_permission_bindings(
    adapter: ModuleAdapterContractV1,
    manifest: ModuleManifestV1,
) -> None:
    manifest_permissions = _permission_keys_for_manifest(manifest)
    bound_permissions = {
        binding.permission_key for binding in adapter.permission_bindings
    }
    used_permissions = _required_permission_keys(adapter)

    for permission_key in used_permissions:
        validate_permission_key(permission_key)
        if permission_key not in manifest_permissions:
            raise ValueError(
                f"{adapter.adapter_key} permission is not in C07 manifest: "
                f"{permission_key}"
            )

    if not used_permissions.issubset(bound_permissions):
        missing = sorted(used_permissions - bound_permissions)
        raise ValueError(
            f"{adapter.adapter_key} permissions are not bound: {missing}"
        )

    for binding in adapter.permission_bindings:
        if binding.module_key != adapter.module_key:
            raise ValueError(f"{adapter.adapter_key} permission module drift.")
        if binding.permission_key not in manifest_permissions:
            raise ValueError(
                f"{adapter.adapter_key} permission binding is not traceable."
            )


def _validate_actions(adapter: ModuleAdapterContractV1) -> None:
    capability_keys = {capability.capability_key for capability in adapter.capabilities}
    action_keys = [action.action_key for action in adapter.actions]
    contract_keys = [contract.action_key for contract in adapter.action_contracts]
    contract_execution_types = {
        contract.action_key: contract.execution_type
        for contract in adapter.action_contracts
    }
    operation_log_actions = {
        binding.action_key: binding.operation_log_action
        for binding in adapter.operation_log_bindings
    }
    input_contract_keys = {
        contract.contract_key for contract in adapter.input_contracts
    }
    output_contract_keys = {
        contract.contract_key for contract in adapter.output_contracts
    }

    if len(action_keys) != len(set(action_keys)):
        raise ValueError(f"{adapter.adapter_key} has duplicate action_key.")
    if set(action_keys) != set(contract_keys):
        raise ValueError(f"{adapter.adapter_key} action contracts drift.")

    for action in adapter.actions:
        if action.module_key != adapter.module_key:
            raise ValueError(f"{adapter.adapter_key} action module_key drift.")
        if action.capability_key not in capability_keys:
            raise ValueError(f"{adapter.adapter_key} action capability drift.")
        validate_permission_key(action.required_permission)
        if not action.risk_level:
            raise ValueError(f"{adapter.adapter_key} action missing risk.")
        if not action.operation_log_action:
            raise ValueError(
                f"{adapter.adapter_key} action missing operation log action."
            )
        if action.execution_type not in SAFE_ADAPTER_EXECUTION_TYPES:
            raise ValueError(
                f"{adapter.adapter_key} action has unsafe execution_type."
            )
        if (
            contract_execution_types.get(action.action_key)
            != action.execution_type
        ):
            raise ValueError(
                f"{adapter.adapter_key} action execution_type drift."
            )
        if action.executable_before_c09:
            raise ValueError(f"{adapter.adapter_key} action is executable.")
        if (
            action.requires_execution_provider
            and not adapter.execution_requirements.requires_execution_provider
        ):
            raise ValueError(
                f"{adapter.adapter_key} execution action lacks requirement."
            )
        if (
            action.requires_approval
            and not adapter.approval_requirements.requires_approval
        ):
            raise ValueError(
                f"{adapter.adapter_key} approval action lacks requirement."
            )
        if operation_log_actions.get(action.action_key) != (
            action.operation_log_action
        ):
            raise ValueError(
                f"{adapter.adapter_key} operation log binding drift."
            )

    for contract in adapter.action_contracts:
        validate_permission_key(contract.required_permission)
        if contract.execution_type not in SAFE_ADAPTER_EXECUTION_TYPES:
            raise ValueError(
                f"{adapter.adapter_key} contract has unsafe execution_type."
            )
        if contract.input_contract not in input_contract_keys:
            raise ValueError(f"{adapter.adapter_key} input contract missing.")
        if contract.output_contract not in output_contract_keys:
            raise ValueError(f"{adapter.adapter_key} output contract missing.")
        if contract.executable_before_c09:
            raise ValueError(f"{adapter.adapter_key} contract is executable.")
        if (
            contract.requires_execution_provider
            and not adapter.execution_requirements.requires_execution_provider
        ):
            raise ValueError(
                f"{adapter.adapter_key} contract lacks execution requirement."
            )


def _validate_dependencies(adapter: ModuleAdapterContractV1) -> None:
    for dependency in adapter.dependency_declarations:
        if dependency.dependency_key not in ALLOWED_ADAPTER_DEPENDENCIES:
            raise ValueError(
                f"{adapter.adapter_key} dependency is not allowed: "
                f"{dependency.dependency_key}"
            )
        if dependency.live_connection_allowed:
            raise ValueError(
                f"{adapter.adapter_key} dependency declares live connection."
            )
        if (
            dependency.dependency_key in LIVE_PROVIDER_DEPENDENCIES
            and dependency.provider_status != "declared_only"
        ):
            raise ValueError(
                f"{adapter.adapter_key} live provider dependency is not safe."
            )
        for value in _iter_string_values(dependency.model_dump()):
            lowered = value.lower()
            if any(marker in lowered for marker in SENSITIVE_VALUE_MARKERS):
                raise ValueError(
                    f"{adapter.adapter_key} dependency contains sensitive data."
                )

    if adapter.status_provider.live_provider_connected:
        raise ValueError(f"{adapter.adapter_key} status provider is live.")
    if adapter.status_provider.secret_read_allowed:
        raise ValueError(f"{adapter.adapter_key} status provider reads secrets.")
    if adapter.health_provider.live_check_allowed:
        raise ValueError(f"{adapter.adapter_key} health provider is live.")
    if adapter.health_provider.secret_read_allowed:
        raise ValueError(f"{adapter.adapter_key} health provider reads secrets.")


def _validate_scope_bindings(adapter: ModuleAdapterContractV1) -> None:
    for binding in adapter.scope_bindings:
        if binding.status != "adapter_pending":
            raise ValueError(
                f"{adapter.adapter_key} scope binding must stay pending."
            )
        if not set(binding.declared_scope_types).issubset(ALLOWED_SCOPE_TYPES):
            raise ValueError(f"{adapter.adapter_key} invalid scope binding.")


def _validate_future_runtime_boundaries(adapter: ModuleAdapterContractV1) -> None:
    lowered_key = f"{adapter.adapter_key} {adapter.module_key}".lower()
    if (
        lowered_key.startswith("k01")
        or ".k01" in lowered_key
        or "product_knowledge" in lowered_key
    ) and adapter.adapter_status not in {"adapter_pending", "disabled", "draft"}:
        raise ValueError(f"{adapter.adapter_key} K01 cannot be enabled.")

    if re.search(r"\bp0[1-8]\b|p_series|product_page_automation", lowered_key):
        if adapter.adapter_status not in {"adapter_pending", "disabled", "draft"}:
            raise ValueError(f"{adapter.adapter_key} P-series cannot be enabled.")

    if adapter.adapter_status in NON_EXECUTABLE_ADAPTER_STATUSES:
        if any(action.executable_before_c09 for action in adapter.actions):
            raise ValueError(
                f"{adapter.adapter_key} non-executable status has action."
            )
    if adapter.execution_requirements.executable_before_c09:
        raise ValueError(
            f"{adapter.adapter_key} execution before C09 is not allowed."
        )
    if (
        adapter.execution_requirements.execution_type
        not in SAFE_ADAPTER_EXECUTION_TYPES
    ):
        raise ValueError(
            f"{adapter.adapter_key} execution requirement has unsafe execution_type."
        )
    if adapter.sandbox_requirements.network_access_allowed:
        raise ValueError(f"{adapter.adapter_key} sandbox allows network.")
    if adapter.sandbox_requirements.file_system_access_allowed:
        raise ValueError(f"{adapter.adapter_key} sandbox allows filesystem.")


def validate_adapter_contracts(
    raw_adapters: Sequence[ModuleAdapterContractV1 | Mapping[str, Any]]
    | None = None,
) -> list[ModuleAdapterContractV1]:
    adapters = [
        _adapter_from_raw(raw_adapter)
        for raw_adapter in (raw_adapters or MODULE_ADAPTER_CONTRACTS_V1)
    ]
    module_manifests = {
        manifest.module_key: manifest for manifest in list_module_manifests()
    }
    seen_keys: set[str] = set()

    for adapter in adapters:
        _validate_adapter_key(adapter.adapter_key)
        if adapter.adapter_key in seen_keys:
            raise ValueError(f"Duplicate adapter_key: {adapter.adapter_key}")
        seen_keys.add(adapter.adapter_key)

        if not ADAPTER_VERSION_PATTERN.fullmatch(adapter.adapter_version):
            raise ValueError(f"{adapter.adapter_key} invalid adapter_version.")
        if adapter.manifest_version != "v1":
            raise ValueError(f"{adapter.adapter_key} invalid manifest_version.")
        if adapter.module_key not in module_manifests:
            raise ValueError(
                f"{adapter.adapter_key} module_key is not registered."
            )
        if adapter.adapter_status not in ALLOWED_ADAPTER_STATUSES:
            raise ValueError(f"{adapter.adapter_key} invalid adapter_status.")
        if not adapter.supported_surfaces:
            raise ValueError(f"{adapter.adapter_key} needs surfaces.")
        if not set(adapter.supported_surfaces).issubset(ALLOWED_ADAPTER_SURFACES):
            raise ValueError(f"{adapter.adapter_key} invalid surfaces.")

        manifest = module_manifests[adapter.module_key]
        _validate_module_binding(adapter, manifest)
        _validate_permission_bindings(adapter, manifest)
        _validate_actions(adapter)
        _validate_dependencies(adapter)
        _validate_scope_bindings(adapter)
        _validate_future_runtime_boundaries(adapter)
        _validate_safe_values(adapter)

    return adapters


def list_adapter_contracts() -> list[ModuleAdapterContractV1]:
    return validate_adapter_contracts()


def get_adapter_contract(adapter_key: str) -> ModuleAdapterContractV1 | None:
    for adapter in list_adapter_contracts():
        if adapter.adapter_key == adapter_key:
            return adapter
    return None


def _missing_permissions(
    required_permissions: set[str],
    current_user_permissions: CurrentUserPermissionInfo,
) -> list[str]:
    if current_user_permissions.is_owner_full_access:
        return []
    permission_keys = set(current_user_permissions.permission_keys)
    if "*" in permission_keys:
        return []
    return sorted(required_permissions - permission_keys)


def _action_keys(adapter: ModuleAdapterContractV1) -> list[str]:
    return [action.action_key for action in adapter.actions]


def _execution_provider_state(
    adapter: ModuleAdapterContractV1,
    access_state: AdapterAccessState,
):
    if access_state == "adapter_pending":
        return "adapter_pending"
    if access_state == "disabled":
        return "disabled"
    if (
        adapter.execution_requirements.requires_execution_provider
        or any(action.requires_execution_provider for action in adapter.actions)
    ):
        return "required_not_implemented_c08b"
    return "not_required"


def build_adapter_access_state(
    adapter: ModuleAdapterContractV1,
    current_user_permissions: CurrentUserPermissionInfo,
) -> ModuleAdapterAccessRead:
    manifest = get_module_manifest(adapter.module_key)
    if manifest is None:
        raise ValueError(f"{adapter.adapter_key} module manifest is missing.")

    module_access = build_module_access_state(manifest, current_user_permissions)
    required_permissions = _required_permission_keys(adapter)
    missing_permissions = _missing_permissions(
        required_permissions,
        current_user_permissions,
    )
    action_keys = _action_keys(adapter)
    requires_execution_provider = (
        adapter.execution_requirements.requires_execution_provider
        or any(action.requires_execution_provider for action in adapter.actions)
    )
    requires_approval = (
        adapter.approval_requirements.requires_approval
        or any(action.requires_approval for action in adapter.actions)
    )

    if module_access.hidden:
        return ModuleAdapterAccessRead(
            adapter_key=adapter.adapter_key,
            module_key=adapter.module_key,
            visible=False,
            hidden=True,
            locked=False,
            unavailable=False,
            adapter_status=adapter.adapter_status,
            adapter_access_state="hidden",
            supported_surfaces=[],
            available_surfaces=[],
            disabled_surfaces=[],
            action_contracts=[],
            available_actions=[],
            locked_actions=[],
            unavailable_actions=[],
            required_permissions=sorted(required_permissions),
            missing_permissions=missing_permissions,
            requires_execution_provider=requires_execution_provider,
            execution_provider_state="not_required",
            requires_approval=requires_approval,
            reason=module_access.reason,
        )

    if module_access.locked:
        return ModuleAdapterAccessRead(
            adapter_key=adapter.adapter_key,
            module_key=adapter.module_key,
            visible=True,
            hidden=False,
            locked=True,
            unavailable=module_access.unavailable,
            adapter_status=adapter.adapter_status,
            adapter_access_state="locked",
            supported_surfaces=adapter.supported_surfaces,
            available_surfaces=[],
            disabled_surfaces=adapter.supported_surfaces,
            action_contracts=adapter.action_contracts,
            available_actions=[],
            locked_actions=action_keys,
            unavailable_actions=[],
            required_permissions=sorted(required_permissions),
            missing_permissions=missing_permissions,
            requires_execution_provider=requires_execution_provider,
            execution_provider_state=_execution_provider_state(
                adapter,
                "locked",
            ),
            requires_approval=requires_approval,
            reason=module_access.reason,
        )

    access_state: AdapterAccessState = "available"
    unavailable = False
    reason = "Adapter contract metadata is available; actions are declarations."

    if adapter.adapter_status == "adapter_pending":
        access_state = "adapter_pending"
        unavailable = True
        reason = "Adapter status is adapter_pending."
    elif adapter.adapter_status == "disabled":
        access_state = "disabled"
        unavailable = True
        reason = "Adapter status is disabled."
    elif adapter.adapter_status in {"draft", "deprecated"}:
        access_state = "unavailable"
        unavailable = True
        reason = f"Adapter status is {adapter.adapter_status}."
    elif module_access.unavailable:
        access_state = "unavailable"
        unavailable = True
        reason = module_access.reason

    if access_state == "available":
        disabled_surfaces = [
            surface
            for surface in adapter.supported_surfaces
            if surface == "action_panel" and action_keys
        ]
        available_surfaces = [
            surface
            for surface in adapter.supported_surfaces
            if surface not in disabled_surfaces
        ]
    else:
        available_surfaces = []
        disabled_surfaces = adapter.supported_surfaces

    return ModuleAdapterAccessRead(
        adapter_key=adapter.adapter_key,
        module_key=adapter.module_key,
        visible=True,
        hidden=False,
        locked=False,
        unavailable=unavailable,
        adapter_status=adapter.adapter_status,
        adapter_access_state=access_state,
        supported_surfaces=adapter.supported_surfaces,
        available_surfaces=available_surfaces,
        disabled_surfaces=disabled_surfaces,
        action_contracts=adapter.action_contracts,
        available_actions=[],
        locked_actions=[],
        unavailable_actions=action_keys,
        required_permissions=sorted(required_permissions),
        missing_permissions=missing_permissions,
        requires_execution_provider=requires_execution_provider,
        execution_provider_state=_execution_provider_state(adapter, access_state),
        requires_approval=requires_approval,
        reason=reason,
    )


def list_adapters_for_user(
    db: Session,
    user: User,
) -> tuple[CurrentUserPermissionInfo, list[ModuleAdapterAccessRead]]:
    current_user_permissions = resolve_current_user_permission_info(db, user)
    return (
        current_user_permissions,
        [
            build_adapter_access_state(adapter, current_user_permissions)
            for adapter in list_adapter_contracts()
        ],
    )
