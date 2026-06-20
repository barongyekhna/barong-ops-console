import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from sqlalchemy.orm import Session

from ..core.execution_providers import EXECUTION_PROVIDER_CONTRACTS_V1
from ..core.permissions import validate_permission_key
from ..models.user import User
from ..schemas.execution_provider import (
    ExecutionActionType,
    ExecutionMode,
    ExecutionProviderAccessRead,
    ExecutionProviderContractV1,
    ExecutionProviderStatus,
    ExecutionProviderType,
)
from ..schemas.module_adapter import ModuleAdapterActionContract
from .module_adapter_registry import (
    build_adapter_access_state,
    get_adapter_contract,
    list_adapter_contracts,
)
from .module_switch_runtime_gate import (
    ModuleSwitchRuntimeBlockedError,
    enforce_module_switch_before_c09_execution_request,
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

PROVIDER_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)+$"
)
PROVIDER_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_PROVIDER_TYPES = frozenset(get_args(ExecutionProviderType))
ALLOWED_PROVIDER_STATUSES = frozenset(get_args(ExecutionProviderStatus))
ALLOWED_EXECUTION_MODES = frozenset(get_args(ExecutionMode))
ALLOWED_ACTION_TYPES = frozenset(get_args(ExecutionActionType))
FUTURE_PROVIDER_TYPES = {
    "local_backend_provider",
    "queue_provider",
    "webhook_provider",
    "scheduled_provider",
    "future_live_provider",
}
FUTURE_PROVIDER_ALLOWED_STATUSES = {
    "draft",
    "mock",
    "staging_ready",
    "live_ready",
    "provider_pending",
    "provider_unavailable",
    "disabled",
    "deprecated",
}
NON_EXECUTABLE_PROVIDER_STATUSES = {
    "draft",
    "provider_pending",
    "provider_unavailable",
    "disabled",
    "deprecated",
}
SENSITIVE_RUNTIME_VALUE_MARKERS = (
    ".env",
    "authorization",
    "bearer ",
    "credential=",
    "credential:",
    "http://",
    "https://",
    "password",
    "provider_url",
    "token=",
    "token:",
    "webhook_url",
    "://",
)


def _provider_from_raw(
    raw: ExecutionProviderContractV1 | Mapping[str, Any],
) -> ExecutionProviderContractV1:
    if isinstance(raw, ExecutionProviderContractV1):
        return raw
    return ExecutionProviderContractV1.model_validate(raw)


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


def _validate_safe_values(provider: ExecutionProviderContractV1) -> None:
    for value in _iter_string_values(provider.model_dump(mode="json")):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_RUNTIME_VALUE_MARKERS):
            raise ValueError(
                f"{provider.provider_key} contains an unsafe runtime value."
            )


def _validate_provider_key(provider_key: str) -> None:
    if not PROVIDER_KEY_PATTERN.fullmatch(provider_key):
        raise ValueError(
            "Provider key must use lowercase snake_case or dot namespace."
        )


def _adapter_action_contract(
    provider: ExecutionProviderContractV1,
) -> ModuleAdapterActionContract:
    adapter = get_adapter_contract(provider.adapter_key)
    if adapter is None:
        raise ValueError(
            f"{provider.provider_key} adapter_key is not registered."
        )
    if adapter.module_key != provider.module_key:
        raise ValueError(f"{provider.provider_key} adapter module_key drift.")
    contract = next(
        (
            action_contract
            for action_contract in adapter.action_contracts
            if action_contract.action_key == provider.action_key
        ),
        None,
    )
    if contract is None:
        raise ValueError(
            f"{provider.provider_key} action_key is not in C08 action_contracts."
        )
    return contract


def _validate_action_binding(provider: ExecutionProviderContractV1) -> None:
    adapter_contract = _adapter_action_contract(provider)
    if provider.required_permissions != [adapter_contract.required_permission]:
        raise ValueError(
            f"{provider.provider_key} required_permission does not match C08."
        )
    if provider.risk_level != adapter_contract.risk_level:
        raise ValueError(f"{provider.provider_key} risk_level does not match C08.")
    if provider.operation_log_action != adapter_contract.operation_log_action:
        raise ValueError(
            f"{provider.provider_key} operation_log_action does not match C08."
        )
    if (
        provider.operation_log_policy.operation_log_action
        != adapter_contract.operation_log_action
    ):
        raise ValueError(
            f"{provider.provider_key} operation_log_policy does not match C08."
        )
    if provider.requires_execution_provider != (
        adapter_contract.requires_execution_provider
    ):
        raise ValueError(
            f"{provider.provider_key} execution requirement does not match C08."
        )

    requires_approval = (
        adapter_contract.requires_approval
        or adapter_contract.risk_level in {"high", "critical"}
    )
    if provider.requires_approval != requires_approval:
        raise ValueError(
            f"{provider.provider_key} approval requirement does not match C08."
        )
    if (
        provider.approval_requirement.requires_approval != requires_approval
        or provider.approval_requirement.blocks_execution_in_c09b
        != requires_approval
    ):
        raise ValueError(
            f"{provider.provider_key} approval policy does not block correctly."
        )

    if adapter_contract.requires_approval and (
        provider.executable or provider.can_request_execution
    ):
        raise ValueError(f"{provider.provider_key} approval action is executable.")
    if adapter_contract.requires_execution_provider:
        if (
            provider.provider_readiness == "live_ready"
            and provider.provider_status
            not in {"provider_pending", "provider_unavailable", "disabled", "live_ready"}
        ):
            raise ValueError(
                f"{provider.provider_key} live execution action is not safely future gated."
            )


def _validate_secret_boundary(provider: ExecutionProviderContractV1) -> None:
    requirement = provider.secret_requirement
    if (
        requirement.secret_value_declared
        or requirement.provider_credential_declared
        or requirement.secret_read_allowed
        or provider.credential_declared
    ):
        raise ValueError(f"{provider.provider_key} declares a secret value.")
    if requirement.requires_secret:
        if requirement.rules_provider_state != "waiting_c14":
            raise ValueError(
                f"{provider.provider_key} secret requirement must wait for C14."
            )
        if not requirement.blocks_execution_in_c09b:
            raise ValueError(
                f"{provider.provider_key} secret requirement must block C09B."
            )


def _validate_no_live_runtime(provider: ExecutionProviderContractV1) -> None:
    if provider.live_provider_connected:
        raise ValueError(f"{provider.provider_key} is live connected.")
    if provider.external_endpoint_declared:
        raise ValueError(f"{provider.provider_key} declares external endpoint.")
    if provider.callback_policy.callback_supported:
        raise ValueError(f"{provider.provider_key} declares callback support.")
    if provider.callback_policy.callback_connected_in_c09b:
        raise ValueError(f"{provider.provider_key} has connected callback.")
    if provider.callback_policy.external_endpoint_declared:
        raise ValueError(f"{provider.provider_key} declares callback endpoint.")
    if provider.artifact_policy.local_path_allowed:
        raise ValueError(f"{provider.provider_key} allows local artifact path.")
    if provider.artifact_policy.external_reference_allowed:
        raise ValueError(
            f"{provider.provider_key} allows external artifact reference."
        )
    if provider.operation_log_policy.writes_operation_logs_in_c09b:
        raise ValueError(f"{provider.provider_key} writes operation logs.")
    if provider.audit_event_policy.writes_audit_events_in_c09b:
        raise ValueError(f"{provider.provider_key} writes audit events.")
    if provider.provider_type in FUTURE_PROVIDER_TYPES:
        if provider.provider_status not in FUTURE_PROVIDER_ALLOWED_STATUSES:
            raise ValueError(
                f"{provider.provider_key} future provider is not pending."
            )
    if provider.provider_status in {"mock", "staging_ready", "live_ready"}:
        if provider.provider_status != provider.provider_readiness:
            raise ValueError(f"{provider.provider_key} readiness status drift.")
    if provider.provider_readiness == "live_ready":
        if provider.provider_type != "future_live_provider":
            raise ValueError(f"{provider.provider_key} live_ready is future only.")
        if provider.can_request_execution:
            raise ValueError(f"{provider.provider_key} live_ready cannot request execution yet.")


def _validate_serializable_schema(provider: ExecutionProviderContractV1) -> None:
    json.dumps(provider.execution_request_schema.model_dump(mode="json"))
    json.dumps(provider.execution_result_schema.model_dump(mode="json"))
    json.dumps(provider.execution_state_schema.model_dump(mode="json"))


def validate_execution_provider_contracts(
    raw_providers: Sequence[ExecutionProviderContractV1 | Mapping[str, Any]]
    | None = None,
) -> list[ExecutionProviderContractV1]:
    providers = [
        _provider_from_raw(raw_provider)
        for raw_provider in (raw_providers or EXECUTION_PROVIDER_CONTRACTS_V1)
    ]
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    adapter_keys = {adapter.adapter_key for adapter in list_adapter_contracts()}
    seen_keys: set[str] = set()

    for provider in providers:
        _validate_provider_key(provider.provider_key)
        if provider.provider_key in seen_keys:
            raise ValueError(f"Duplicate provider_key: {provider.provider_key}")
        seen_keys.add(provider.provider_key)
        if not PROVIDER_VERSION_PATTERN.fullmatch(provider.provider_version):
            raise ValueError(f"{provider.provider_key} invalid provider_version.")
        if provider.provider_type not in ALLOWED_PROVIDER_TYPES:
            raise ValueError(f"{provider.provider_key} invalid provider_type.")
        if provider.provider_status not in ALLOWED_PROVIDER_STATUSES:
            raise ValueError(f"{provider.provider_key} invalid provider_status.")
        if provider.lifecycle not in ALLOWED_PROVIDER_STATUSES:
            raise ValueError(f"{provider.provider_key} invalid lifecycle.")
        if not provider.supported_execution_modes:
            raise ValueError(f"{provider.provider_key} needs execution modes.")
        if not set(provider.supported_execution_modes).issubset(
            ALLOWED_EXECUTION_MODES
        ):
            raise ValueError(f"{provider.provider_key} invalid execution mode.")
        if not provider.supported_action_types:
            raise ValueError(f"{provider.provider_key} needs action types.")
        if not set(provider.supported_action_types).issubset(ALLOWED_ACTION_TYPES):
            raise ValueError(f"{provider.provider_key} invalid action type.")
        if not MODULE_KEY_PATTERN.fullmatch(provider.module_key):
            raise ValueError(f"{provider.provider_key} invalid module_key.")
        if provider.module_key not in module_keys:
            raise ValueError(
                f"{provider.provider_key} module_key is not registered."
            )
        if provider.adapter_key not in adapter_keys:
            raise ValueError(
                f"{provider.provider_key} adapter_key is not registered."
            )
        for permission_key in provider.required_permissions:
            validate_permission_key(permission_key)
        if not provider.operation_log_action:
            raise ValueError(f"{provider.provider_key} missing operation log.")
        _validate_action_binding(provider)
        if provider.provider_status in NON_EXECUTABLE_PROVIDER_STATUSES:
            if provider.executable or provider.can_request_execution:
                raise ValueError(
                    f"{provider.provider_key} non-executable status can execute."
                )
        if provider.provider_status == "contract_ready":
            if provider.executable or provider.can_request_execution:
                raise ValueError(
                    f"{provider.provider_key} contract_ready can execute."
                )
        if provider.provider_status == "test_ready":
            if provider.executable or provider.can_request_execution:
                raise ValueError(
                    f"{provider.provider_key} test_ready can execute."
                )
        _validate_secret_boundary(provider)
        _validate_no_live_runtime(provider)
        _validate_serializable_schema(provider)
        _validate_safe_values(provider)

    return providers


def list_execution_provider_contracts() -> list[ExecutionProviderContractV1]:
    return validate_execution_provider_contracts()


def get_execution_provider_contract(
    provider_key: str,
) -> ExecutionProviderContractV1 | None:
    for provider in list_execution_provider_contracts():
        if provider.provider_key == provider_key:
            return provider
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


def _provider_status_access_state(provider_status: str) -> str | None:
    if provider_status == "provider_pending":
        return "provider_pending"
    if provider_status == "disabled":
        return "disabled"
    if provider_status == "deprecated":
        return "deprecated"
    if provider_status in {"draft", "provider_unavailable"}:
        return "unavailable"
    return None


def _resolved_mode_for_readiness(provider: ExecutionProviderContractV1) -> str:
    if provider.provider_readiness == "staging_ready":
        return "staging"
    if provider.provider_readiness == "live_ready":
        return "live"
    return "mock"


def _access_message(block_reason: str) -> str:
    messages = {
        "hidden": "Execution provider metadata is hidden by module or adapter access.",
        "missing_permission": "Missing required permission for this provider action.",
        "blocked_approval_required": "Waiting for C12 Approval Gate.",
        "secret_rules_required": "Waiting for C14 Secret Rules.",
        "scope_adapter_pending": "Waiting for C18 scope adapter.",
        "provider_pending": "Provider is pending and cannot execute in C09B.",
        "disabled": "Provider is disabled and cannot execute.",
        "deprecated": "Provider is deprecated and cannot execute.",
        "provider_unavailable": "Provider is unavailable and cannot execute.",
        "execution_provider_required": "Execution provider is required, but C09B is no-execute.",
        "router_selection_required": "Execution requests must enter the ExecutionRouter.",
        "live_mode_future_gated": "Live provider execution remains future-gated.",
        "no_execute_c09b": "Execution Provider contract is readable; execution is disabled in C09B.",
    }
    return messages.get(block_reason, messages["no_execute_c09b"])


def build_execution_provider_access_state(
    provider: ExecutionProviderContractV1,
    current_user_permissions: CurrentUserPermissionInfo,
) -> ExecutionProviderAccessRead:
    try:
        enforce_module_switch_before_c09_execution_request(provider.module_key)
    except ModuleSwitchRuntimeBlockedError as exc:
        return ExecutionProviderAccessRead(
            provider_key=provider.provider_key,
            provider_type=provider.provider_type,
            provider_status=provider.provider_status,
            provider_readiness=provider.provider_readiness,
            provider_access_state="blocked",
            module_key=provider.module_key,
            adapter_key=provider.adapter_key,
            action_key=provider.action_key,
            visible=True,
            hidden=False,
            locked=False,
            unavailable=True,
            blocked=True,
            block_reason=exc.decision.reason,
            required_permission=provider.required_permissions[0],
            missing_permissions=[],
            risk_level=provider.risk_level,
            requires_approval=provider.approval_requirement.requires_approval,
            approval_status=provider.approval_requirement.approval_status,
            requires_secret=provider.secret_requirement.requires_secret,
            secret_binding_status=provider.secret_requirement.secret_binding_status,
            requires_scope=provider.scope_requirement.requires_scope,
            scope_status=provider.scope_requirement.scope_status,
            execution_mode=provider.supported_execution_modes[0],
            resolved_execution_mode=_resolved_mode_for_readiness(provider),
            can_request_execution=False,
            executable=False,
            no_execute_reason="blocked_by_module_switch",
            operation_log_action=provider.operation_log_action,
            safe_status_message=str(exc),
        )

    manifest = get_module_manifest(provider.module_key)
    if manifest is None:
        raise ValueError(f"{provider.provider_key} module manifest is missing.")
    adapter = get_adapter_contract(provider.adapter_key)
    if adapter is None:
        raise ValueError(f"{provider.provider_key} adapter is missing.")
    action_contract = _adapter_action_contract(provider)
    module_access = build_module_access_state(manifest, current_user_permissions)
    adapter_access = build_adapter_access_state(adapter, current_user_permissions)
    required_permissions = set(provider.required_permissions)
    missing_permissions = _missing_permissions(
        required_permissions,
        current_user_permissions,
    )

    hidden = module_access.hidden or adapter_access.hidden
    locked = module_access.locked or adapter_access.locked or bool(missing_permissions)
    if hidden:
        return ExecutionProviderAccessRead(
            provider_key=provider.provider_key,
            provider_type=provider.provider_type,
            provider_status=provider.provider_status,
            provider_readiness=provider.provider_readiness,
            provider_access_state="hidden",
            module_key=provider.module_key,
            adapter_key=provider.adapter_key,
            action_key=provider.action_key,
            visible=False,
            hidden=True,
            locked=False,
            unavailable=False,
            blocked=True,
            block_reason="hidden",
            required_permission=provider.required_permissions[0],
            missing_permissions=missing_permissions,
            risk_level=provider.risk_level,
            requires_approval=provider.approval_requirement.requires_approval,
            approval_status=provider.approval_requirement.approval_status,
            requires_secret=provider.secret_requirement.requires_secret,
            secret_binding_status=provider.secret_requirement.secret_binding_status,
            requires_scope=provider.scope_requirement.requires_scope,
            scope_status=provider.scope_requirement.scope_status,
            execution_mode=provider.supported_execution_modes[0],
            resolved_execution_mode=_resolved_mode_for_readiness(provider),
            can_request_execution=False,
            executable=False,
            no_execute_reason="hidden",
            operation_log_action=provider.operation_log_action,
            safe_status_message=_access_message("hidden"),
        )

    if locked:
        return ExecutionProviderAccessRead(
            provider_key=provider.provider_key,
            provider_type=provider.provider_type,
            provider_status=provider.provider_status,
            provider_readiness=provider.provider_readiness,
            provider_access_state="locked",
            module_key=provider.module_key,
            adapter_key=provider.adapter_key,
            action_key=provider.action_key,
            visible=True,
            hidden=False,
            locked=True,
            unavailable=module_access.unavailable or adapter_access.unavailable,
            blocked=True,
            block_reason="missing_permission",
            required_permission=provider.required_permissions[0],
            missing_permissions=missing_permissions,
            risk_level=provider.risk_level,
            requires_approval=provider.approval_requirement.requires_approval,
            approval_status=provider.approval_requirement.approval_status,
            requires_secret=provider.secret_requirement.requires_secret,
            secret_binding_status=provider.secret_requirement.secret_binding_status,
            requires_scope=provider.scope_requirement.requires_scope,
            scope_status=provider.scope_requirement.scope_status,
            execution_mode=provider.supported_execution_modes[0],
            resolved_execution_mode=_resolved_mode_for_readiness(provider),
            can_request_execution=False,
            executable=False,
            no_execute_reason="missing_permission",
            operation_log_action=provider.operation_log_action,
            safe_status_message=_access_message("missing_permission"),
        )

    status_state = _provider_status_access_state(provider.provider_status)
    unavailable = (
        module_access.unavailable
        or adapter_access.unavailable
        or status_state is not None
    )
    provider_access_state = "visible"
    block_reason = "router_selection_required"
    no_execute_reason = "execution_router_required"
    blocked = False
    can_request_execution = bool(provider.can_request_execution)

    if provider.approval_requirement.requires_approval:
        blocked = True
        can_request_execution = False
        provider_access_state = "blocked"
        block_reason = "blocked_approval_required"
        no_execute_reason = "waiting_c12_approval_gate"
    elif provider.secret_requirement.requires_secret:
        blocked = True
        can_request_execution = False
        provider_access_state = "blocked"
        block_reason = "secret_rules_required"
        no_execute_reason = "waiting_c14_secret_rules"
    elif provider.scope_requirement.requires_scope:
        blocked = True
        can_request_execution = False
        provider_access_state = "blocked"
        block_reason = "scope_adapter_pending"
        no_execute_reason = "waiting_c18_scope_adapter"
    elif status_state is not None:
        blocked = True
        can_request_execution = False
        provider_access_state = status_state
        if provider.provider_status == "provider_unavailable":
            block_reason = "provider_unavailable"
            no_execute_reason = "provider_unavailable"
        else:
            block_reason = status_state
            no_execute_reason = status_state
    elif provider.provider_readiness == "live_ready":
        blocked = True
        can_request_execution = False
        provider_access_state = "blocked"
        block_reason = "live_mode_future_gated"
        no_execute_reason = "live_provider_future_only"
    elif action_contract.requires_execution_provider and not provider.can_request_execution:
        blocked = True
        provider_access_state = "blocked"
        block_reason = "execution_provider_required"
        no_execute_reason = "execution_router_required"

    if unavailable:
        blocked = True
        can_request_execution = False
    if provider_access_state == "blocked" and unavailable:
        provider_access_state = "unavailable"

    return ExecutionProviderAccessRead(
        provider_key=provider.provider_key,
        provider_type=provider.provider_type,
        provider_status=provider.provider_status,
        provider_readiness=provider.provider_readiness,
        provider_access_state=provider_access_state,
        module_key=provider.module_key,
        adapter_key=provider.adapter_key,
        action_key=provider.action_key,
        visible=True,
        hidden=False,
        locked=False,
        unavailable=unavailable,
        blocked=blocked,
        block_reason=block_reason,
        required_permission=provider.required_permissions[0],
        missing_permissions=[],
        risk_level=provider.risk_level,
        requires_approval=provider.approval_requirement.requires_approval,
        approval_status=provider.approval_requirement.approval_status,
        requires_secret=provider.secret_requirement.requires_secret,
        secret_binding_status=provider.secret_requirement.secret_binding_status,
        requires_scope=provider.scope_requirement.requires_scope,
        scope_status=provider.scope_requirement.scope_status,
        execution_mode=provider.supported_execution_modes[0],
        resolved_execution_mode=_resolved_mode_for_readiness(provider),
        can_request_execution=can_request_execution,
        executable=False,
        no_execute_reason=no_execute_reason,
        operation_log_action=provider.operation_log_action,
        safe_status_message=_access_message(block_reason),
    )


def list_execution_providers_for_user(
    db: Session,
    user: User,
    *,
    request: object | None = None,
) -> tuple[CurrentUserPermissionInfo, list[ExecutionProviderAccessRead]]:
    current_user_permissions = resolve_current_user_permission_info(
        db,
        user,
        request=request,
    )
    return (
        current_user_permissions,
        [
            build_execution_provider_access_state(
                provider,
                current_user_permissions,
            )
            for provider in list_execution_provider_contracts()
        ],
    )
