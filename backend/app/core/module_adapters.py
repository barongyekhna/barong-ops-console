from typing import Any


def _page(
    *,
    page_key: str,
    module_key: str,
    surface: str,
    route: str,
    route_namespace: str,
    status: str,
    unavailable_behavior: str,
    required_permission: str | None = None,
    component_ref: str | None = None,
    data_contract_refs: tuple[str, ...] = (),
    action_refs: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "page_key": page_key,
        "module_key": module_key,
        "surface": surface,
        "route": route,
        "route_namespace": route_namespace,
        "required_permission": required_permission,
        "status": status,
        "unavailable_behavior": unavailable_behavior,
        "component_ref": component_ref,
        "data_contract_refs": list(data_contract_refs),
        "action_refs": list(action_refs),
    }


def _nav(
    *,
    nav_key: str,
    module_key: str,
    label: str,
    group: str,
    icon: str,
    order: int,
    route: str,
    denied_behavior: str,
    unavailable_behavior: str,
    required_permission: str | None = None,
    default_visible: bool = True,
    owner_only: bool = False,
) -> dict[str, object]:
    return {
        "nav_key": nav_key,
        "module_key": module_key,
        "label": label,
        "group": group,
        "icon": icon,
        "order": order,
        "route": route,
        "required_permission": required_permission,
        "denied_behavior": denied_behavior,
        "unavailable_behavior": unavailable_behavior,
        "default_visible": default_visible,
        "owner_only": owner_only,
    }


def _route(
    *,
    route_key: str,
    module_key: str,
    path: str,
    route_namespace: str,
    surface: str,
    status: str,
    required_permission: str | None = None,
    guard_policy: str = "module_access_state",
) -> dict[str, object]:
    return {
        "route_key": route_key,
        "module_key": module_key,
        "path": path,
        "route_namespace": route_namespace,
        "surface": surface,
        "required_permission": required_permission,
        "guard_policy": guard_policy,
        "status": status,
    }


def _api(
    *,
    api_key: str,
    module_key: str,
    api_namespace: str,
    path: str,
    method: str,
    status: str,
    required_permission: str | None = None,
    no_api: bool = False,
) -> dict[str, object]:
    return {
        "api_key": api_key,
        "module_key": module_key,
        "api_namespace": api_namespace,
        "path": path,
        "method": method,
        "required_permission": required_permission,
        "status": status,
        "no_api": no_api,
    }


def _capability(
    *,
    capability_key: str,
    module_key: str,
    display_name: str,
    description: str,
    required_permission: str | None = None,
    surfaces: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "capability_key": capability_key,
        "module_key": module_key,
        "display_name": display_name,
        "description": description,
        "required_permission": required_permission,
        "surfaces": list(surfaces),
    }


def _action(
    *,
    action_key: str,
    module_key: str,
    capability_key: str,
    display_name: str,
    description: str,
    required_permission: str,
    risk_level: str,
    operation_log_action: str,
    status: str,
    execution_type: str = "mock",
    requires_approval: bool = False,
    requires_execution_provider: bool = False,
) -> dict[str, object]:
    return {
        "action_key": action_key,
        "module_key": module_key,
        "capability_key": capability_key,
        "display_name": display_name,
        "description": description,
        "required_permission": required_permission,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "requires_execution_provider": requires_execution_provider,
        "operation_log_action": operation_log_action,
        "execution_type": execution_type,
        "executable_before_c09": False,
        "status": status,
    }


def _action_contract(
    *,
    action_key: str,
    input_contract: str,
    output_contract: str,
    required_permission: str,
    risk_level: str,
    operation_log_action: str,
    execution_type: str = "mock",
    requires_approval: bool = False,
    requires_execution_provider: bool = False,
    execution_requirement_ref: str | None = None,
    audit_event_refs: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "action_key": action_key,
        "input_contract": input_contract,
        "output_contract": output_contract,
        "required_permission": required_permission,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "requires_execution_provider": requires_execution_provider,
        "execution_requirement_ref": execution_requirement_ref,
        "operation_log_action": operation_log_action,
        "execution_type": execution_type,
        "audit_event_refs": list(audit_event_refs),
        "idempotency_policy": "declared_only",
        "timeout_policy": "declared_only",
        "fallback_behavior": "unavailable_before_c09",
        "executable_before_c09": False,
    }


def _status_provider(module_key: str) -> dict[str, object]:
    return {
        "provider_key": f"{module_key}.status",
        "module_key": module_key,
        "status_contract": f"{module_key}.status.v1",
        "allowed_statuses": [
            "adapter_pending",
            "contract_ready",
            "provider_not_connected",
            "execution_not_connected",
            "disabled",
            "available",
            "degraded",
        ],
        "source": "static_adapter_registry",
        "live_provider_connected": False,
        "last_checked_at_policy": "not_checked_in_c08b",
        "safe_message_policy": "safe_static_message_only",
        "secret_read_allowed": False,
    }


def _health_provider(module_key: str) -> dict[str, object]:
    return {
        "provider_key": f"{module_key}.health",
        "module_key": module_key,
        "health_contract": f"{module_key}.health.v1",
        "checks": ["contract_shape"],
        "mock_only": True,
        "live_check_allowed": False,
        "secret_read_allowed": False,
        "safe_failure_behavior": "show_unavailable",
    }


def _data_contract(
    *,
    contract_key: str,
    module_key: str,
    object_type: str,
    read_boundary: tuple[str, ...],
    write_boundary: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "contract_key": contract_key,
        "contract_version": "1.0.0",
        "module_key": module_key,
        "object_type": object_type,
        "schema_ref": f"{contract_key}.schema",
        "read_boundary": list(read_boundary),
        "write_boundary": list(write_boundary),
        "owner_module": module_key,
        "version_policy": "versioned_contract",
        "test_fixture_path": None,
        "breaking_change_policy": "new_contract_version_required",
    }


def _input_contract(
    *,
    contract_key: str,
    action_key: str | None,
    required_fields: tuple[str, ...] = (),
    optional_fields: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "contract_key": contract_key,
        "action_key": action_key,
        "schema_ref": f"{contract_key}.schema",
        "required_fields": list(required_fields),
        "optional_fields": list(optional_fields),
        "validation_rules": ["declared_only"],
        "sensitive_fields": [],
        "redaction_policy": "safe_fields_only",
    }


def _output_contract(
    *,
    contract_key: str,
    action_key: str | None,
    safe_summary_fields: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "contract_key": contract_key,
        "action_key": action_key,
        "schema_ref": f"{contract_key}.schema",
        "safe_summary_fields": list(safe_summary_fields),
        "sensitive_fields": [],
        "redaction_policy": "safe_fields_only",
        "operation_log_projection": list(safe_summary_fields),
    }


def _permission_binding(
    *,
    permission_key: str,
    module_key: str,
    used_by: str,
    risk_level: str,
    surface: str | None = None,
    action_key: str | None = None,
) -> dict[str, object]:
    return {
        "permission_key": permission_key,
        "module_key": module_key,
        "used_by": used_by,
        "surface": surface,
        "action_key": action_key,
        "risk_level": risk_level,
        "required": True,
        "registry_status": "registered",
        "pending_registration_reason": None,
    }


def _scope_binding() -> dict[str, object]:
    return {
        "status": "adapter_pending",
        "declared_scope_types": ["global", "module"],
        "requires_c18_scope_adapter": True,
        "default_scope_policy": "use_c05_c06_effective_permissions_before_c18",
        "scope_validation_ref": "future_c18_scope_adapter",
        "fallback_before_c18": "global_or_module_scope_only",
    }


def _operation_log_binding(
    *,
    action_key: str,
    operation_log_action: str,
    target_type: str,
) -> dict[str, object]:
    return {
        "action_key": action_key,
        "operation_log_action": operation_log_action,
        "target_type": target_type,
        "target_id_policy": "declared_by_future_execution_provider",
        "details_projection": ["action_key", "result"],
        "redaction_policy": "safe_fields_only",
        "result_values": ["success", "blocked", "failed"],
        "failure_values": ["blocked", "failed"],
        "rollback_action": None,
    }


def _feature_flag(
    *,
    feature_flag_key: str,
    module_key: str,
) -> dict[str, object]:
    return {
        "feature_flag_key": feature_flag_key,
        "module_key": module_key,
        "status": "declared_only",
        "switch_provider_state": "not_implemented_c08b",
    }


def _execution_requirements(
    *,
    requires_execution_provider: bool,
    provider_contract_ref: str | None = None,
    execution_type: str = "no_op",
) -> dict[str, object]:
    return {
        "requires_execution_provider": requires_execution_provider,
        "executable_before_c09": False,
        "execution_type": execution_type,
        "execution_provider_state": (
            "required_not_implemented_c08b"
            if requires_execution_provider
            else "not_required"
        ),
        "provider_contract_ref": provider_contract_ref,
        "queue_required": requires_execution_provider,
        "result_contract_ref": None,
    }


def _sandbox_requirements(*, sandbox_required: bool) -> dict[str, object]:
    return {
        "sandbox_required": sandbox_required,
        "status": "declared_only" if sandbox_required else "not_required",
        "data_boundary_ref": None,
        "network_access_allowed": False,
        "file_system_access_allowed": False,
    }


def _approval_requirements(*, requires_approval: bool) -> dict[str, object]:
    return {
        "requires_approval": requires_approval,
        "high_risk_action_policy": (
            "future_c12_required" if requires_approval else "not_required"
        ),
        "approval_provider_state": "not_implemented_c08b",
        "approval_reason_required": requires_approval,
    }


def _fallback_behavior() -> dict[str, str]:
    return {
        "adapter_missing": "module_unavailable",
        "provider_missing": "provider_not_connected",
        "execution_missing": "execution_not_connected",
        "permission_missing": "use_c07_denied_behavior",
    }


def _test_contract(test_key: str) -> dict[str, object]:
    return {
        "test_key": test_key,
        "description": "C08B static adapter contract validation.",
        "required": True,
    }


def _adapter(
    *,
    adapter_key: str,
    module_key: str,
    display_name: str,
    description: str,
    adapter_status: str,
    lifecycle: str,
    supported_surfaces: tuple[str, ...],
    pages: tuple[dict[str, object], ...],
    nav_bindings: tuple[dict[str, object], ...],
    route_bindings: tuple[dict[str, object], ...],
    api_bindings: tuple[dict[str, object], ...],
    capabilities: tuple[dict[str, object], ...],
    actions: tuple[dict[str, object], ...],
    action_contracts: tuple[dict[str, object], ...],
    data_contracts: tuple[dict[str, object], ...],
    input_contracts: tuple[dict[str, object], ...],
    output_contracts: tuple[dict[str, object], ...],
    permission_bindings: tuple[dict[str, object], ...],
    operation_log_bindings: tuple[dict[str, object], ...],
    dependency_declarations: tuple[dict[str, object], ...] = (),
    feature_flag_bindings: tuple[dict[str, object], ...] = (),
    audit_events: tuple[dict[str, object], ...] = (),
    execution_type: str = "mock",
    requires_execution_provider: bool = False,
    requires_sandbox: bool = False,
    requires_approval: bool = False,
    unavailable_behavior: str = "show_unavailable",
    docs_path: str = "docs/C08_MODULE_ADAPTER_BACKEND.md",
) -> dict[str, Any]:
    return {
        "adapter_key": adapter_key,
        "adapter_version": "1.0.0",
        "module_key": module_key,
        "manifest_version": "v1",
        "display_name": display_name,
        "description": description,
        "adapter_status": adapter_status,
        "lifecycle": lifecycle,
        "supported_surfaces": list(supported_surfaces),
        "pages": list(pages),
        "nav_bindings": list(nav_bindings),
        "route_bindings": list(route_bindings),
        "api_bindings": list(api_bindings),
        "capabilities": list(capabilities),
        "actions": list(actions),
        "action_contracts": list(action_contracts),
        "status_provider": _status_provider(module_key),
        "health_provider": _health_provider(module_key),
        "data_contracts": list(data_contracts),
        "input_contracts": list(input_contracts),
        "output_contracts": list(output_contracts),
        "permission_bindings": list(permission_bindings),
        "scope_bindings": [_scope_binding()],
        "operation_log_bindings": list(operation_log_bindings),
        "audit_events": list(audit_events),
        "feature_flag_bindings": list(feature_flag_bindings),
        "dependency_declarations": list(dependency_declarations),
        "execution_requirements": _execution_requirements(
            requires_execution_provider=requires_execution_provider,
            provider_contract_ref=(
                f"{module_key}.execution.v1"
                if requires_execution_provider
                else None
            ),
            execution_type=execution_type,
        ),
        "sandbox_requirements": _sandbox_requirements(
            sandbox_required=requires_sandbox
        ),
        "approval_requirements": _approval_requirements(
            requires_approval=requires_approval
        ),
        "secret_requirements": [],
        "fallback_behavior": _fallback_behavior(),
        "unavailable_behavior": unavailable_behavior,
        "test_contracts": [_test_contract("c08b.adapter.contract")],
        "docs_path": docs_path,
    }


MODULE_ADAPTER_CONTRACTS_V1: tuple[dict[str, Any], ...] = (
    _adapter(
        adapter_key="core.dashboard.adapter",
        module_key="core.dashboard",
        display_name="Dashboard Adapter",
        description="Read-only dashboard shell adapter contract.",
        adapter_status="sealed",
        lifecycle="sealed",
        supported_surfaces=("navigation", "dashboard_card", "status_widget"),
        pages=(
            _page(
                page_key="core.dashboard.index",
                module_key="core.dashboard",
                surface="dashboard_card",
                route="/dashboard",
                route_namespace="/dashboard",
                status="sealed",
                unavailable_behavior="hide",
                component_ref="builtin.dashboard_shell",
                data_contract_refs=("core.dashboard.summary.v1",),
            ),
        ),
        nav_bindings=(
            _nav(
                nav_key="core.dashboard.main",
                module_key="core.dashboard",
                label="Dashboard",
                group="Overview",
                icon="LayoutDashboard",
                order=10,
                route="/dashboard",
                denied_behavior="hide_when_denied",
                unavailable_behavior="hide",
            ),
        ),
        route_bindings=(
            _route(
                route_key="core.dashboard.index",
                module_key="core.dashboard",
                path="/dashboard",
                route_namespace="/dashboard",
                surface="dashboard_card",
                status="sealed",
            ),
        ),
        api_bindings=(
            _api(
                api_key="core.dashboard.no_api",
                module_key="core.dashboard",
                api_namespace="no_api",
                path="no_api",
                method="NO_API",
                status="sealed",
                no_api=True,
            ),
        ),
        capabilities=(
            _capability(
                capability_key="core.dashboard.view",
                module_key="core.dashboard",
                display_name="View dashboard shell",
                description="View safe dashboard shell metadata.",
                surfaces=("dashboard_card", "status_widget"),
            ),
        ),
        actions=(),
        action_contracts=(),
        data_contracts=(
            _data_contract(
                contract_key="core.dashboard.summary.v1",
                module_key="core.dashboard",
                object_type="dashboard_summary",
                read_boundary=("module_access_state",),
            ),
        ),
        input_contracts=(),
        output_contracts=(
            _output_contract(
                contract_key="core.dashboard.summary.output.v1",
                action_key=None,
                safe_summary_fields=("module_key", "access_state"),
            ),
        ),
        permission_bindings=(),
        operation_log_bindings=(),
        execution_type="no_op",
        unavailable_behavior="hide",
    ),
    _adapter(
        adapter_key="admin.users.adapter",
        module_key="admin.users",
        display_name="User Management Adapter",
        description="Owner-only user management adapter contract metadata.",
        adapter_status="sealed",
        lifecycle="sealed",
        supported_surfaces=(
            "navigation",
            "module_page",
            "detail_page",
            "action_panel",
            "audit_log_view",
            "status_widget",
        ),
        pages=(
            _page(
                page_key="admin.users.index",
                module_key="admin.users",
                surface="module_page",
                route="/users",
                route_namespace="/users",
                required_permission="users.read",
                status="sealed",
                unavailable_behavior="show_unavailable",
                component_ref="builtin.user_management_shell",
                data_contract_refs=("admin.users.account.v1",),
                action_refs=("admin.users.read", "admin.users.manage"),
            ),
        ),
        nav_bindings=(
            _nav(
                nav_key="admin.users.main",
                module_key="admin.users",
                label="User Management",
                group="System",
                icon="UserRoundCog",
                order=10,
                route="/users",
                required_permission="users.manage",
                denied_behavior="hide_when_denied",
                unavailable_behavior="show_unavailable",
                owner_only=True,
            ),
        ),
        route_bindings=(
            _route(
                route_key="admin.users.index",
                module_key="admin.users",
                path="/users",
                route_namespace="/users",
                surface="module_page",
                required_permission="users.read",
                status="sealed",
            ),
        ),
        api_bindings=(
            _api(
                api_key="admin.users.list",
                module_key="admin.users",
                api_namespace="/users",
                path="/users",
                method="GET",
                required_permission="users.read",
                status="sealed",
            ),
        ),
        capabilities=(
            _capability(
                capability_key="admin.users.read",
                module_key="admin.users",
                display_name="Read user metadata",
                description="Read safe user account metadata.",
                required_permission="users.read",
                surfaces=("module_page", "detail_page"),
            ),
            _capability(
                capability_key="admin.users.manage",
                module_key="admin.users",
                display_name="Manage user lifecycle",
                description="Declare owner-only user lifecycle actions.",
                required_permission="users.manage",
                surfaces=("action_panel", "audit_log_view"),
            ),
        ),
        actions=(
            _action(
                action_key="admin.users.read",
                module_key="admin.users",
                capability_key="admin.users.read",
                display_name="Read users",
                description="Declare user metadata read contract.",
                required_permission="users.read",
                risk_level="medium",
                operation_log_action="user.read",
                execution_type="mock",
                status="sealed",
            ),
            _action(
                action_key="admin.users.manage",
                module_key="admin.users",
                capability_key="admin.users.manage",
                display_name="Manage users",
                description="Declare owner-only user lifecycle contract.",
                required_permission="users.manage",
                risk_level="high",
                operation_log_action="user.manage",
                execution_type="mock",
                status="sealed",
                requires_approval=True,
            ),
        ),
        action_contracts=(
            _action_contract(
                action_key="admin.users.read",
                input_contract="admin.users.read.input.v1",
                output_contract="admin.users.read.output.v1",
                required_permission="users.read",
                risk_level="medium",
                operation_log_action="user.read",
                execution_type="mock",
            ),
            _action_contract(
                action_key="admin.users.manage",
                input_contract="admin.users.manage.input.v1",
                output_contract="admin.users.manage.output.v1",
                required_permission="users.manage",
                risk_level="high",
                operation_log_action="user.manage",
                execution_type="mock",
                requires_approval=True,
            ),
        ),
        data_contracts=(
            _data_contract(
                contract_key="admin.users.account.v1",
                module_key="admin.users",
                object_type="safe_user_account",
                read_boundary=("users",),
                write_boundary=("users",),
            ),
        ),
        input_contracts=(
            _input_contract(
                contract_key="admin.users.read.input.v1",
                action_key="admin.users.read",
            ),
            _input_contract(
                contract_key="admin.users.manage.input.v1",
                action_key="admin.users.manage",
                optional_fields=("username", "role", "is_active"),
            ),
        ),
        output_contracts=(
            _output_contract(
                contract_key="admin.users.read.output.v1",
                action_key="admin.users.read",
                safe_summary_fields=("id", "username", "role", "is_active"),
            ),
            _output_contract(
                contract_key="admin.users.manage.output.v1",
                action_key="admin.users.manage",
                safe_summary_fields=("id", "username", "operation_id"),
            ),
        ),
        permission_bindings=(
            _permission_binding(
                permission_key="users.read",
                module_key="admin.users",
                used_by="page:admin.users.index",
                surface="module_page",
                risk_level="medium",
            ),
            _permission_binding(
                permission_key="users.manage",
                module_key="admin.users",
                used_by="action:admin.users.manage",
                action_key="admin.users.manage",
                surface="action_panel",
                risk_level="high",
            ),
        ),
        operation_log_bindings=(
            _operation_log_binding(
                action_key="admin.users.read",
                operation_log_action="user.read",
                target_type="user",
            ),
            _operation_log_binding(
                action_key="admin.users.manage",
                operation_log_action="user.manage",
                target_type="user",
            ),
        ),
        execution_type="mock",
        requires_approval=True,
    ),
    _adapter(
        adapter_key="admin.permissions.adapter",
        module_key="admin.permissions",
        display_name="Permission Management Adapter",
        description="Owner-only permission management adapter contract.",
        adapter_status="sealed",
        lifecycle="sealed",
        supported_surfaces=(
            "navigation",
            "module_page",
            "action_panel",
            "audit_log_view",
            "status_widget",
        ),
        pages=(
            _page(
                page_key="admin.permissions.index",
                module_key="admin.permissions",
                surface="module_page",
                route="/users/permissions",
                route_namespace="/users",
                required_permission="permissions.read",
                status="sealed",
                unavailable_behavior="show_unavailable",
                component_ref="builtin.permission_management_shell",
                data_contract_refs=("admin.permissions.assignment.v1",),
                action_refs=(
                    "admin.permissions.read",
                    "admin.permissions.manage",
                ),
            ),
        ),
        nav_bindings=(
            _nav(
                nav_key="admin.permissions.main",
                module_key="admin.permissions",
                label="Permission Management",
                group="System",
                icon="LockKeyhole",
                order=20,
                route="/users",
                required_permission="permissions.read",
                denied_behavior="hide_when_denied",
                unavailable_behavior="show_unavailable",
                default_visible=False,
                owner_only=True,
            ),
        ),
        route_bindings=(
            _route(
                route_key="admin.permissions.index",
                module_key="admin.permissions",
                path="/users/permissions",
                route_namespace="/users",
                surface="module_page",
                required_permission="permissions.read",
                status="sealed",
            ),
        ),
        api_bindings=(
            _api(
                api_key="admin.permissions.current_user",
                module_key="admin.permissions",
                api_namespace="/permissions",
                path="/permissions/me",
                method="GET",
                required_permission="permissions.read",
                status="sealed",
            ),
            _api(
                api_key="admin.permissions.registry",
                module_key="admin.permissions",
                api_namespace="/permissions",
                path="/permissions/registry",
                method="GET",
                required_permission="permissions.read",
                status="sealed",
            ),
        ),
        capabilities=(
            _capability(
                capability_key="admin.permissions.read",
                module_key="admin.permissions",
                display_name="Read permission metadata",
                description="Read safe permission registry and assignments.",
                required_permission="permissions.read",
                surfaces=("module_page", "audit_log_view"),
            ),
            _capability(
                capability_key="admin.permissions.manage",
                module_key="admin.permissions",
                display_name="Manage permission assignments",
                description="Declare owner-only permission assignment actions.",
                required_permission="permissions.manage",
                surfaces=("action_panel", "audit_log_view"),
            ),
        ),
        actions=(
            _action(
                action_key="admin.permissions.read",
                module_key="admin.permissions",
                capability_key="admin.permissions.read",
                display_name="Read permissions",
                description="Declare permission metadata read contract.",
                required_permission="permissions.read",
                risk_level="medium",
                operation_log_action="permission.read",
                execution_type="mock",
                status="sealed",
            ),
            _action(
                action_key="admin.permissions.manage",
                module_key="admin.permissions",
                capability_key="admin.permissions.manage",
                display_name="Manage permissions",
                description="Declare owner-only permission assignment contract.",
                required_permission="permissions.manage",
                risk_level="critical",
                operation_log_action="permission.assignment.manage",
                execution_type="mock",
                status="sealed",
                requires_approval=True,
            ),
        ),
        action_contracts=(
            _action_contract(
                action_key="admin.permissions.read",
                input_contract="admin.permissions.read.input.v1",
                output_contract="admin.permissions.read.output.v1",
                required_permission="permissions.read",
                risk_level="medium",
                operation_log_action="permission.read",
                execution_type="mock",
            ),
            _action_contract(
                action_key="admin.permissions.manage",
                input_contract="admin.permissions.manage.input.v1",
                output_contract="admin.permissions.manage.output.v1",
                required_permission="permissions.manage",
                risk_level="critical",
                operation_log_action="permission.assignment.manage",
                execution_type="mock",
                requires_approval=True,
            ),
        ),
        data_contracts=(
            _data_contract(
                contract_key="admin.permissions.assignment.v1",
                module_key="admin.permissions",
                object_type="permission_assignment",
                read_boundary=(
                    "permission_registry",
                    "user_permission_assignments",
                ),
                write_boundary=("user_permission_assignments",),
            ),
        ),
        input_contracts=(
            _input_contract(
                contract_key="admin.permissions.read.input.v1",
                action_key="admin.permissions.read",
            ),
            _input_contract(
                contract_key="admin.permissions.manage.input.v1",
                action_key="admin.permissions.manage",
                required_fields=("permission_key", "reason"),
                optional_fields=("scope_type", "scope_key", "expires_at"),
            ),
        ),
        output_contracts=(
            _output_contract(
                contract_key="admin.permissions.read.output.v1",
                action_key="admin.permissions.read",
                safe_summary_fields=("permission_key", "risk_level"),
            ),
            _output_contract(
                contract_key="admin.permissions.manage.output.v1",
                action_key="admin.permissions.manage",
                safe_summary_fields=("assignment_id", "operation_id"),
            ),
        ),
        permission_bindings=(
            _permission_binding(
                permission_key="permissions.read",
                module_key="admin.permissions",
                used_by="page:admin.permissions.index",
                surface="module_page",
                risk_level="medium",
            ),
            _permission_binding(
                permission_key="permissions.manage",
                module_key="admin.permissions",
                used_by="action:admin.permissions.manage",
                action_key="admin.permissions.manage",
                surface="action_panel",
                risk_level="critical",
            ),
        ),
        operation_log_bindings=(
            _operation_log_binding(
                action_key="admin.permissions.read",
                operation_log_action="permission.read",
                target_type="permission",
            ),
            _operation_log_binding(
                action_key="admin.permissions.manage",
                operation_log_action="permission.assignment.manage",
                target_type="permission_assignment",
            ),
        ),
        execution_type="mock",
        requires_approval=True,
    ),
    _adapter(
        adapter_key="k.product_knowledge.adapter",
        module_key="k.product_knowledge",
        display_name="K Product Knowledge Adapter",
        description=(
            "Production K-series product knowledge adapter for product CRUD, "
            "keyword/risk governance, media metadata, and provider-gated "
            "enrichment flows."
        ),
        adapter_status="production_ready",
        lifecycle="production_ready",
        supported_surfaces=(
            "navigation",
            "module_page",
            "detail_page",
            "action_panel",
            "status_widget",
        ),
        pages=(
            _page(
                page_key="k.product_knowledge.products",
                module_key="k.product_knowledge",
                surface="module_page",
                route="/products",
                route_namespace="/products",
                required_permission="k.product_knowledge.read",
                status="production_ready",
                unavailable_behavior="show_unavailable",
                component_ref="modules.k.product_knowledge.ProductList",
                data_contract_refs=("k.product_knowledge.product.v1",),
                action_refs=(
                    "k.product_knowledge.prompt.execute",
                    "k.product_knowledge.serp.execute",
                    "k.product_knowledge.ai_enrich.execute",
                    "k.product_knowledge.risk_filter.execute",
                ),
            ),
        ),
        nav_bindings=(
            _nav(
                nav_key="k.product_knowledge.main",
                module_key="k.product_knowledge",
                label="产品知识库",
                group="Registry",
                icon="PackageSearch",
                order=8,
                route="/products",
                required_permission="k.product_knowledge.read",
                denied_behavior="show_locked",
                unavailable_behavior="show_unavailable",
            ),
        ),
        route_bindings=(
            _route(
                route_key="k.product_knowledge.products",
                module_key="k.product_knowledge",
                path="/products",
                route_namespace="/products",
                surface="module_page",
                required_permission="k.product_knowledge.read",
                status="production_ready",
            ),
        ),
        api_bindings=(
            _api(
                api_key="k.product_knowledge.products.list",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/products",
                method="GET",
                status="production_ready",
                required_permission="k.product_knowledge.read",
            ),
            _api(
                api_key="k.product_knowledge.products.create",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/products",
                method="POST",
                status="production_ready",
                required_permission="k.product_knowledge.create",
            ),
            _api(
                api_key="k.product_knowledge.products.update",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/products/{product_id}",
                method="PATCH",
                status="production_ready",
                required_permission="k.product_knowledge.update",
            ),
            _api(
                api_key="k.product_knowledge.keywords",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/keywords",
                method="POST",
                status="production_ready",
                required_permission="k.product_knowledge.keywords.manage",
            ),
            _api(
                api_key="k.product_knowledge.research",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/keyword-research/start",
                method="POST",
                status="production_ready",
                required_permission="k.product_knowledge.keywords.manage",
            ),
            _api(
                api_key="k.product_knowledge.serp",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/serp/search",
                method="POST",
                status="production_ready",
                required_permission="k.product_knowledge.keywords.manage",
            ),
            _api(
                api_key="k.product_knowledge.risk",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/risk",
                method="POST",
                status="production_ready",
                required_permission="k.product_knowledge.risk_terms.manage",
            ),
            _api(
                api_key="k.product_knowledge.media",
                module_key="k.product_knowledge",
                api_namespace="/k",
                path="/k/media",
                method="POST",
                status="production_ready",
                required_permission="k.product_knowledge.update",
            ),
        ),
        capabilities=(
            _capability(
                capability_key="k.product_knowledge.product_crud",
                module_key="k.product_knowledge",
                display_name="Manage product knowledge",
                description="Create and update persistent K product knowledge records.",
                required_permission="k.product_knowledge.read",
                surfaces=("module_page", "detail_page"),
            ),
            _capability(
                capability_key="k.product_knowledge.provider_execution",
                module_key="k.product_knowledge",
                display_name="Run product enrichment",
                description="Execute provider-gated prompt, SERP, AI enrichment, and risk filtering flows.",
                required_permission="k.product_knowledge.update",
                surfaces=("action_panel", "status_widget"),
            ),
        ),
        actions=(
            _action(
                action_key="k.product_knowledge.prompt.execute",
                module_key="k.product_knowledge",
                capability_key="k.product_knowledge.provider_execution",
                display_name="Execute product prompt",
                description="Run an API-key-gated product prompt through the K module runtime.",
                required_permission="k.product_knowledge.update",
                risk_level="medium",
                operation_log_action="k.product_knowledge.prompt.execute",
                execution_type="no_op",
                status="production_ready",
                requires_execution_provider=True,
            ),
            _action(
                action_key="k.product_knowledge.serp.execute",
                module_key="k.product_knowledge",
                capability_key="k.product_knowledge.provider_execution",
                display_name="Execute SERP lookup",
                description="Run API-key-gated SERP keyword research.",
                required_permission="k.product_knowledge.keywords.manage",
                risk_level="medium",
                operation_log_action="k.product_knowledge.serp.execute",
                execution_type="no_op",
                status="production_ready",
                requires_execution_provider=True,
            ),
            _action(
                action_key="k.product_knowledge.ai_enrich.execute",
                module_key="k.product_knowledge",
                capability_key="k.product_knowledge.provider_execution",
                display_name="Execute AI enrichment",
                description="Run API-key-gated DeepSeek or AI provider enrichment.",
                required_permission="k.product_knowledge.update",
                risk_level="medium",
                operation_log_action="k.product_knowledge.ai_enrich.execute",
                execution_type="no_op",
                status="production_ready",
                requires_execution_provider=True,
            ),
            _action(
                action_key="k.product_knowledge.risk_filter.execute",
                module_key="k.product_knowledge",
                capability_key="k.product_knowledge.provider_execution",
                display_name="Execute risk filtering",
                description="Run API-key-gated risk keyword detection and filtering.",
                required_permission="k.product_knowledge.risk_terms.manage",
                risk_level="high",
                operation_log_action="k.product_knowledge.risk_filter.execute",
                execution_type="no_op",
                status="production_ready",
                requires_execution_provider=True,
                requires_approval=True,
            ),
        ),
        action_contracts=(
            _action_contract(
                action_key="k.product_knowledge.prompt.execute",
                input_contract="k.product_knowledge.prompt.input.v1",
                output_contract="k.product_knowledge.prompt.output.v1",
                required_permission="k.product_knowledge.update",
                risk_level="medium",
                operation_log_action="k.product_knowledge.prompt.execute",
                execution_type="no_op",
                requires_execution_provider=True,
                execution_requirement_ref="k.product_knowledge.execution.v1",
            ),
            _action_contract(
                action_key="k.product_knowledge.serp.execute",
                input_contract="k.product_knowledge.serp.input.v1",
                output_contract="k.product_knowledge.serp.output.v1",
                required_permission="k.product_knowledge.keywords.manage",
                risk_level="medium",
                operation_log_action="k.product_knowledge.serp.execute",
                execution_type="no_op",
                requires_execution_provider=True,
                execution_requirement_ref="k.product_knowledge.execution.v1",
            ),
            _action_contract(
                action_key="k.product_knowledge.ai_enrich.execute",
                input_contract="k.product_knowledge.ai_enrich.input.v1",
                output_contract="k.product_knowledge.ai_enrich.output.v1",
                required_permission="k.product_knowledge.update",
                risk_level="medium",
                operation_log_action="k.product_knowledge.ai_enrich.execute",
                execution_type="no_op",
                requires_execution_provider=True,
                execution_requirement_ref="k.product_knowledge.execution.v1",
            ),
            _action_contract(
                action_key="k.product_knowledge.risk_filter.execute",
                input_contract="k.product_knowledge.risk_filter.input.v1",
                output_contract="k.product_knowledge.risk_filter.output.v1",
                required_permission="k.product_knowledge.risk_terms.manage",
                risk_level="high",
                operation_log_action="k.product_knowledge.risk_filter.execute",
                execution_type="no_op",
                requires_execution_provider=True,
                requires_approval=True,
                execution_requirement_ref="k.product_knowledge.execution.v1",
            ),
        ),
        data_contracts=(
            _data_contract(
                contract_key="k.product_knowledge.product.v1",
                module_key="k.product_knowledge",
                object_type="k_product_knowledge_product",
                read_boundary=(
                    "k_product_knowledge_products",
                    "k_product_knowledge_keywords",
                    "k_product_knowledge_risk_terms",
                ),
                write_boundary=(
                    "k_product_knowledge_products",
                    "k_product_knowledge_keywords",
                    "k_product_knowledge_risk_terms",
                    "k_product_knowledge_ai_events",
                ),
            ),
        ),
        input_contracts=(
            _input_contract(
                contract_key="k.product_knowledge.prompt.input.v1",
                action_key="k.product_knowledge.prompt.execute",
                required_fields=("product_id", "prompt"),
            ),
            _input_contract(
                contract_key="k.product_knowledge.serp.input.v1",
                action_key="k.product_knowledge.serp.execute",
                required_fields=("product_id", "query", "market"),
            ),
            _input_contract(
                contract_key="k.product_knowledge.ai_enrich.input.v1",
                action_key="k.product_knowledge.ai_enrich.execute",
                required_fields=("product_id", "provider_alias"),
            ),
            _input_contract(
                contract_key="k.product_knowledge.risk_filter.input.v1",
                action_key="k.product_knowledge.risk_filter.execute",
                required_fields=("product_id",),
            ),
        ),
        output_contracts=(
            _output_contract(
                contract_key="k.product_knowledge.prompt.output.v1",
                action_key="k.product_knowledge.prompt.execute",
                safe_summary_fields=("product_id", "provider", "status"),
            ),
            _output_contract(
                contract_key="k.product_knowledge.serp.output.v1",
                action_key="k.product_knowledge.serp.execute",
                safe_summary_fields=("product_id", "provider", "keyword_count"),
            ),
            _output_contract(
                contract_key="k.product_knowledge.ai_enrich.output.v1",
                action_key="k.product_knowledge.ai_enrich.execute",
                safe_summary_fields=("product_id", "provider", "status"),
            ),
            _output_contract(
                contract_key="k.product_knowledge.risk_filter.output.v1",
                action_key="k.product_knowledge.risk_filter.execute",
                safe_summary_fields=("product_id", "provider", "risk_count"),
            ),
        ),
        permission_bindings=(
            _permission_binding(
                permission_key="k.product_knowledge.read",
                module_key="k.product_knowledge",
                used_by="surface:products",
                surface="module_page",
                risk_level="low",
            ),
            _permission_binding(
                permission_key="k.product_knowledge.create",
                module_key="k.product_knowledge",
                used_by="api:k.product_knowledge.products.create",
                surface="module_page",
                risk_level="medium",
            ),
            _permission_binding(
                permission_key="k.product_knowledge.update",
                module_key="k.product_knowledge",
                used_by="action:k.product_knowledge.ai_enrich.execute",
                action_key="k.product_knowledge.ai_enrich.execute",
                surface="action_panel",
                risk_level="medium",
            ),
            _permission_binding(
                permission_key="k.product_knowledge.archive",
                module_key="k.product_knowledge",
                used_by="api:k.product_knowledge.products.archive",
                surface="detail_page",
                risk_level="high",
            ),
            _permission_binding(
                permission_key="k.product_knowledge.attributes.manage",
                module_key="k.product_knowledge",
                used_by="api:k.product_knowledge.attributes",
                surface="detail_page",
                risk_level="medium",
            ),
            _permission_binding(
                permission_key="k.product_knowledge.keywords.manage",
                module_key="k.product_knowledge",
                used_by="action:k.product_knowledge.serp.execute",
                action_key="k.product_knowledge.serp.execute",
                surface="action_panel",
                risk_level="medium",
            ),
            _permission_binding(
                permission_key="k.product_knowledge.risk_terms.manage",
                module_key="k.product_knowledge",
                used_by="action:k.product_knowledge.risk_filter.execute",
                action_key="k.product_knowledge.risk_filter.execute",
                surface="action_panel",
                risk_level="high",
            ),
            _permission_binding(
                permission_key="k.product_knowledge.update",
                module_key="k.product_knowledge",
                used_by="action:k.product_knowledge.prompt.execute",
                action_key="k.product_knowledge.prompt.execute",
                surface="action_panel",
                risk_level="medium",
            ),
        ),
        operation_log_bindings=(
            _operation_log_binding(
                action_key="k.product_knowledge.prompt.execute",
                operation_log_action="k.product_knowledge.prompt.execute",
                target_type="k_product",
            ),
            _operation_log_binding(
                action_key="k.product_knowledge.serp.execute",
                operation_log_action="k.product_knowledge.serp.execute",
                target_type="k_product",
            ),
            _operation_log_binding(
                action_key="k.product_knowledge.ai_enrich.execute",
                operation_log_action="k.product_knowledge.ai_enrich.execute",
                target_type="k_product",
            ),
            _operation_log_binding(
                action_key="k.product_knowledge.risk_filter.execute",
                operation_log_action="k.product_knowledge.risk_filter.execute",
                target_type="k_product",
            ),
        ),
        dependency_declarations=(
            {
                "dependency_key": "serp",
                "dependency_type": "external_provider",
                "required": False,
                "provider_status": "declared_only",
                "provider_contract_ref": "k.product_knowledge.serp.provider.v1",
                "secret_requirement_ref": None,
                "live_connection_allowed": False,
                "safe_unavailable_message": "SERP provider key binding is required before execution.",
            },
            {
                "dependency_key": "deepseek",
                "dependency_type": "external_provider",
                "required": False,
                "provider_status": "declared_only",
                "provider_contract_ref": "k.product_knowledge.deepseek.provider.v1",
                "secret_requirement_ref": None,
                "live_connection_allowed": False,
                "safe_unavailable_message": "DeepSeek key binding is required before execution.",
            },
            {
                "dependency_key": "ai_provider",
                "dependency_type": "external_provider",
                "required": False,
                "provider_status": "declared_only",
                "provider_contract_ref": "k.product_knowledge.ai.provider.v1",
                "secret_requirement_ref": None,
                "live_connection_allowed": False,
                "safe_unavailable_message": "AI provider key binding is required before execution.",
            },
            {
                "dependency_key": "n8n",
                "dependency_type": "automation",
                "required": False,
                "provider_status": "declared_only",
                "provider_contract_ref": "k.product_knowledge.downstream.workflow.v1",
                "secret_requirement_ref": None,
                "live_connection_allowed": False,
                "safe_unavailable_message": "Downstream workflow binding is required before handoff.",
            },
        ),
        requires_execution_provider=True,
        requires_sandbox=True,
        requires_approval=True,
        execution_type="no_op",
        unavailable_behavior="show_unavailable",
    ),
    _adapter(
        adapter_key="business.products.placeholder.adapter",
        module_key="business.products",
        display_name="Products Placeholder Adapter",
        description="Planned product workspace adapter placeholder.",
        adapter_status="adapter_pending",
        lifecycle="adapter_pending",
        supported_surfaces=(
            "navigation",
            "module_page",
            "action_panel",
            "status_widget",
        ),
        pages=(
            _page(
                page_key="business.products.placeholder",
                module_key="business.products",
                surface="module_page",
                route="/products",
                route_namespace="/products",
                required_permission="products.read",
                status="adapter_pending",
                unavailable_behavior="adapter_pending",
                component_ref="placeholder.products_shell",
                data_contract_refs=("business.products.placeholder.v1",),
                action_refs=("business.products.placeholder.prepare",),
            ),
        ),
        nav_bindings=(
            _nav(
                nav_key="business.products.main",
                module_key="business.products",
                label="Products",
                group="Registry",
                icon="Package",
                order=10,
                route="/products",
                required_permission="products.read",
                denied_behavior="show_locked",
                unavailable_behavior="planned",
            ),
        ),
        route_bindings=(
            _route(
                route_key="business.products.placeholder",
                module_key="business.products",
                path="/products",
                route_namespace="/products",
                surface="module_page",
                required_permission="products.read",
                status="adapter_pending",
            ),
        ),
        api_bindings=(
            _api(
                api_key="business.products.no_api",
                module_key="business.products",
                api_namespace="no_api",
                path="no_api",
                method="NO_API",
                status="adapter_pending",
                no_api=True,
            ),
        ),
        capabilities=(
            _capability(
                capability_key="business.products.placeholder",
                module_key="business.products",
                display_name="View product placeholder",
                description="Declare future product workspace placeholder.",
                required_permission="products.read",
                surfaces=("module_page", "status_widget"),
            ),
        ),
        actions=(
            _action(
                action_key="business.products.placeholder.prepare",
                module_key="business.products",
                capability_key="business.products.placeholder",
                display_name="Prepare product workspace",
                description="Declare future product workspace preparation.",
                required_permission="products.read",
                risk_level="medium",
                operation_log_action="business.products.placeholder.prepare",
                execution_type="mock",
                status="adapter_pending",
                requires_execution_provider=True,
            ),
        ),
        action_contracts=(
            _action_contract(
                action_key="business.products.placeholder.prepare",
                input_contract="business.products.placeholder.input.v1",
                output_contract="business.products.placeholder.output.v1",
                required_permission="products.read",
                risk_level="medium",
                operation_log_action="business.products.placeholder.prepare",
                execution_type="mock",
                requires_execution_provider=True,
                execution_requirement_ref="business.products.execution.v1",
            ),
        ),
        data_contracts=(
            _data_contract(
                contract_key="business.products.placeholder.v1",
                module_key="business.products",
                object_type="product_placeholder",
                read_boundary=("module_metadata",),
            ),
        ),
        input_contracts=(
            _input_contract(
                contract_key="business.products.placeholder.input.v1",
                action_key="business.products.placeholder.prepare",
            ),
        ),
        output_contracts=(
            _output_contract(
                contract_key="business.products.placeholder.output.v1",
                action_key="business.products.placeholder.prepare",
                safe_summary_fields=("module_key", "adapter_status"),
            ),
        ),
        permission_bindings=(
            _permission_binding(
                permission_key="products.read",
                module_key="business.products",
                used_by="action:business.products.placeholder.prepare",
                action_key="business.products.placeholder.prepare",
                surface="action_panel",
                risk_level="medium",
            ),
        ),
        operation_log_bindings=(
            _operation_log_binding(
                action_key="business.products.placeholder.prepare",
                operation_log_action="business.products.placeholder.prepare",
                target_type="product_placeholder",
            ),
        ),
        feature_flag_bindings=(
            _feature_flag(
                feature_flag_key="modules.business.products",
                module_key="business.products",
            ),
        ),
        execution_type="mock",
        requires_execution_provider=True,
        requires_sandbox=True,
        unavailable_behavior="adapter_pending",
    ),
    _adapter(
        adapter_key="integration.n8n_test_bridge.adapter",
        module_key="integration.n8n_test_bridge",
        display_name="n8n Test Bridge Adapter",
        description="Test-only bridge adapter declaration with no live n8n connection.",
        adapter_status="adapter_pending",
        lifecycle="adapter_pending",
        supported_surfaces=(
            "navigation",
            "module_page",
            "action_panel",
            "status_widget",
        ),
        pages=(
            _page(
                page_key="integration.n8n_test_bridge.index",
                module_key="integration.n8n_test_bridge",
                surface="module_page",
                route="/n8n-test",
                route_namespace="/n8n-test",
                required_permission="modules.read",
                status="adapter_pending",
                unavailable_behavior="adapter_pending",
                component_ref="placeholder.n8n_test_bridge_shell",
                data_contract_refs=("integration.n8n_test_bridge.status.v1",),
                action_refs=("integration.n8n_test_bridge.test_run.declare",),
            ),
        ),
        nav_bindings=(
            _nav(
                nav_key="integration.n8n_test_bridge.main",
                module_key="integration.n8n_test_bridge",
                label="n8n Test Bridge",
                group="Overview",
                icon="Workflow",
                order=30,
                route="/n8n-test",
                required_permission="modules.read",
                denied_behavior="hide_when_denied",
                unavailable_behavior="adapter_pending",
                default_visible=False,
            ),
        ),
        route_bindings=(
            _route(
                route_key="integration.n8n_test_bridge.index",
                module_key="integration.n8n_test_bridge",
                path="/n8n-test",
                route_namespace="/n8n-test",
                surface="module_page",
                required_permission="modules.read",
                status="adapter_pending",
            ),
        ),
        api_bindings=(
            _api(
                api_key="integration.n8n_test_bridge.no_api",
                module_key="integration.n8n_test_bridge",
                api_namespace="no_api",
                path="no_api",
                method="NO_API",
                status="adapter_pending",
                no_api=True,
            ),
        ),
        capabilities=(
            _capability(
                capability_key="integration.n8n_test_bridge.declare",
                module_key="integration.n8n_test_bridge",
                display_name="Declare test bridge",
                description="Declare the existing test-only bridge contract.",
                required_permission="modules.read",
                surfaces=("module_page", "status_widget"),
            ),
        ),
        actions=(
            _action(
                action_key="integration.n8n_test_bridge.test_run.declare",
                module_key="integration.n8n_test_bridge",
                capability_key="integration.n8n_test_bridge.declare",
                display_name="Declare test run",
                description="Declare test bridge run contract only.",
                required_permission="modules.read",
                risk_level="medium",
                operation_log_action="n8n_test.run",
                execution_type="no_op",
                status="adapter_pending",
                requires_execution_provider=True,
            ),
        ),
        action_contracts=(
            _action_contract(
                action_key="integration.n8n_test_bridge.test_run.declare",
                input_contract="integration.n8n_test_bridge.input.v1",
                output_contract="integration.n8n_test_bridge.output.v1",
                required_permission="modules.read",
                risk_level="medium",
                operation_log_action="n8n_test.run",
                execution_type="no_op",
                requires_execution_provider=True,
                execution_requirement_ref="integration.n8n_test_bridge.execution.v1",
            ),
        ),
        data_contracts=(
            _data_contract(
                contract_key="integration.n8n_test_bridge.status.v1",
                module_key="integration.n8n_test_bridge",
                object_type="test_bridge_status",
                read_boundary=("module_metadata",),
            ),
        ),
        input_contracts=(
            _input_contract(
                contract_key="integration.n8n_test_bridge.input.v1",
                action_key="integration.n8n_test_bridge.test_run.declare",
            ),
        ),
        output_contracts=(
            _output_contract(
                contract_key="integration.n8n_test_bridge.output.v1",
                action_key="integration.n8n_test_bridge.test_run.declare",
                safe_summary_fields=("module_key", "adapter_status"),
            ),
        ),
        permission_bindings=(
            _permission_binding(
                permission_key="modules.read",
                module_key="integration.n8n_test_bridge",
                used_by="action:integration.n8n_test_bridge.test_run.declare",
                action_key="integration.n8n_test_bridge.test_run.declare",
                surface="action_panel",
                risk_level="medium",
            ),
        ),
        operation_log_bindings=(
            _operation_log_binding(
                action_key="integration.n8n_test_bridge.test_run.declare",
                operation_log_action="n8n_test.run",
                target_type="n8n_test_bridge",
            ),
        ),
        dependency_declarations=(
            {
                "dependency_key": "n8n",
                "dependency_type": "integration",
                "required": False,
                "provider_status": "declared_only",
                "provider_contract_ref": "integration.n8n_test_bridge.provider.v1",
                "secret_requirement_ref": None,
                "live_connection_allowed": False,
                "safe_unavailable_message": (
                    "n8n is declared for test-only metadata and is not connected."
                ),
            },
        ),
        feature_flag_bindings=(
            _feature_flag(
                feature_flag_key="modules.integration.n8n_test_bridge",
                module_key="integration.n8n_test_bridge",
            ),
        ),
        requires_execution_provider=True,
        requires_sandbox=True,
        execution_type="no_op",
        unavailable_behavior="adapter_pending",
    ),
)
