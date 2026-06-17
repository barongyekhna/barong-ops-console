from typing import Any


REQUEST_SCHEMA_FIELDS = [
    "execution_id",
    "request_id",
    "idempotency_key",
    "module_key",
    "adapter_key",
    "action_key",
    "actor_user_id",
    "target_scope",
    "input_payload",
    "sanitized_input_summary",
    "provider_key",
    "provider_type",
    "status",
    "risk_level",
    "required_permission",
    "approval_status",
    "secret_binding_status",
    "created_at",
    "accepted_at",
    "started_at",
    "finished_at",
    "cancelled_at",
    "timeout_at",
    "result_summary",
    "artifact_refs",
    "error_code",
    "error_message_safe",
    "operation_log_id",
]
RESULT_SCHEMA_FIELDS = [
    "execution_id",
    "provider_key",
    "status",
    "result_summary",
    "artifact_refs",
    "error_code",
    "error_message_safe",
    "operation_log_id",
    "safe_result_only",
]
STATE_SCHEMA_FIELDS = [
    "current_status",
    "allowed_statuses",
    "blocked_statuses",
    "terminal_statuses",
    "transition_policy",
    "executable_in_c09b",
]
EXECUTION_STATUS_VALUES = [
    "draft",
    "requested",
    "blocked_permission",
    "blocked_approval_required",
    "blocked_provider_unavailable",
    "accepted",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "retry_scheduled",
    "skipped",
    "rejected",
    "archived",
]


def _schema(
    *,
    schema_key: str,
    model_name: str,
    fields: list[str],
    required_fields: tuple[str, ...],
    status_values: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "schema_key": schema_key,
        "schema_version": "1.0.0",
        "model_name": model_name,
        "fields": fields,
        "required_fields": list(required_fields),
        "optional_fields": [
            field for field in fields if field not in set(required_fields)
        ],
        "status_values": list(status_values),
        "serialization_policy": "json_serializable_safe_contract",
        "persistence_policy": "contract_only_no_persistence",
        "redaction_policy": "safe_fields_only",
    }


def _request_schema(provider_key: str) -> dict[str, object]:
    return _schema(
        schema_key=f"{provider_key}.request.v1",
        model_name="ExecutionRequestContractV1",
        fields=REQUEST_SCHEMA_FIELDS,
        required_fields=(
            "execution_id",
            "request_id",
            "idempotency_key",
            "module_key",
            "adapter_key",
            "action_key",
            "actor_user_id",
            "provider_key",
            "provider_type",
            "status",
            "risk_level",
            "required_permission",
        ),
        status_values=tuple(EXECUTION_STATUS_VALUES),
    )


def _result_schema(provider_key: str) -> dict[str, object]:
    return _schema(
        schema_key=f"{provider_key}.result.v1",
        model_name="ExecutionResultContractV1",
        fields=RESULT_SCHEMA_FIELDS,
        required_fields=("execution_id", "provider_key", "status"),
        status_values=tuple(EXECUTION_STATUS_VALUES),
    )


def _state_schema(provider_key: str) -> dict[str, object]:
    return _schema(
        schema_key=f"{provider_key}.state.v1",
        model_name="ExecutionStateContractV1",
        fields=STATE_SCHEMA_FIELDS,
        required_fields=("current_status", "allowed_statuses"),
        status_values=tuple(EXECUTION_STATUS_VALUES),
    )


def _approval_requirement(*, requires_approval: bool) -> dict[str, object]:
    return {
        "requires_approval": requires_approval,
        "approval_status": (
            "blocked_approval_required" if requires_approval else "not_required"
        ),
        "approval_provider_state": "waiting_c12" if requires_approval else "not_required",
        "blocks_execution_in_c09b": requires_approval,
        "reason": (
            "C12 Approval Gate is required before this action can execute."
            if requires_approval
            else "Approval is not required by the C08 action contract."
        ),
    }


def _secret_requirement(*, requires_secret: bool) -> dict[str, object]:
    return {
        "requires_secret": requires_secret,
        "secret_binding_status": (
            "secret_rules_required" if requires_secret else "not_required"
        ),
        "secret_value_declared": False,
        "provider_credential_declared": False,
        "secret_read_allowed": False,
        "rules_provider_state": "waiting_c14" if requires_secret else "not_required",
        "blocks_execution_in_c09b": requires_secret,
        "reason": (
            "C14 Secret Rules must define binding and read policy first."
            if requires_secret
            else "No provider secret is required for this contract."
        ),
    }


def _scope_requirement(*, requires_scope: bool) -> dict[str, object]:
    return {
        "requires_scope": requires_scope,
        "scope_status": "scope_adapter_pending" if requires_scope else "not_required",
        "allowed_scope_types": ["global", "module"] if requires_scope else [],
        "requires_c18_scope_adapter": requires_scope,
        "blocks_execution_in_c09b": requires_scope,
        "reason": (
            "C18 scope adapter is required before scoped execution."
            if requires_scope
            else "No formal scope requirement is declared for this provider."
        ),
    }


def _policy(policy_key: str, description: str) -> dict[str, object]:
    return {
        "policy_key": policy_key,
        "description": description,
        "c09b_behavior": "declared_only_no_execution_request_created",
        "enabled_in_c09b": False,
    }


def _operation_log_policy(
    *,
    operation_log_action: str,
) -> dict[str, object]:
    return {
        "operation_log_action": operation_log_action,
        "write_policy": "declared_only",
        "writes_operation_logs_in_c09b": False,
        "details_projection": [
            "module_key",
            "adapter_key",
            "action_key",
            "provider_key",
            "status",
            "risk_level",
            "required_permission",
        ],
        "redaction_policy": "safe_fields_only",
    }


def _fallback_behavior() -> dict[str, str]:
    return {
        "permission_missing": "blocked_permission",
        "approval_missing": "blocked_approval_required_waiting_c12",
        "secret_missing": "secret_rules_required_waiting_c14",
        "scope_missing": "scope_adapter_pending_waiting_c18",
        "provider_missing": "blocked_provider_unavailable",
    }


def _unavailable_behavior(
    *,
    block_reason: str = "no_execute_c09b_contract_only",
) -> dict[str, object]:
    return {
        "block_reason": block_reason,
        "safe_status_message": (
            "Execution Provider contract is readable, but execution is disabled in C09B."
        ),
        "show_to_user": True,
    }


def _test_contract(test_key: str, description: str) -> dict[str, object]:
    return {
        "test_key": test_key,
        "description": description,
        "required": True,
    }


def _provider(
    *,
    provider_key: str,
    provider_type: str,
    provider_status: str,
    provider_readiness: str,
    lifecycle: str,
    display_name: str,
    description: str,
    supported_execution_modes: tuple[str, ...],
    supported_action_types: tuple[str, ...],
    module_key: str,
    adapter_key: str,
    action_key: str,
    required_permission: str,
    risk_level: str,
    operation_log_action: str,
    requires_execution_provider: bool = False,
    requires_approval: bool = False,
    requires_secret: bool = False,
    requires_scope: bool = False,
    unavailable_reason: str = "no_execute_c09b_contract_only",
    can_request_execution: bool = False,
) -> dict[str, Any]:
    return {
        "provider_key": provider_key,
        "provider_version": "1.0.0",
        "provider_type": provider_type,
        "provider_status": provider_status,
        "provider_readiness": provider_readiness,
        "lifecycle": lifecycle,
        "display_name": display_name,
        "description": description,
        "supported_execution_modes": list(supported_execution_modes),
        "supported_action_types": list(supported_action_types),
        "module_key": module_key,
        "adapter_key": adapter_key,
        "action_key": action_key,
        "execution_request_schema": _request_schema(provider_key),
        "execution_result_schema": _result_schema(provider_key),
        "execution_state_schema": _state_schema(provider_key),
        "required_permissions": [required_permission],
        "risk_level": risk_level,
        "approval_requirement": _approval_requirement(
            requires_approval=requires_approval
        ),
        "secret_requirement": _secret_requirement(requires_secret=requires_secret),
        "scope_requirement": _scope_requirement(requires_scope=requires_scope),
        "idempotency_policy": _policy(
            f"{provider_key}.idempotency",
            "Idempotency key shape is declared for future request handling.",
        ),
        "retry_policy": _policy(
            f"{provider_key}.retry",
            "Retry behavior is declared and cannot schedule work in C09B.",
        ),
        "timeout_policy": _policy(
            f"{provider_key}.timeout",
            "Timeout behavior is declared and cannot start timers in C09B.",
        ),
        "cancellation_policy": _policy(
            f"{provider_key}.cancellation",
            "Cancellation behavior is declared for future queued or running states.",
        ),
        "concurrency_policy": _policy(
            f"{provider_key}.concurrency",
            "Concurrency limits are declared and not enforced by runtime execution in C09B.",
        ),
        "rate_limit_policy": _policy(
            f"{provider_key}.rate_limit",
            "Rate-limit behavior is declared for future execution request submission.",
        ),
        "operation_log_policy": _operation_log_policy(
            operation_log_action=operation_log_action
        ),
        "audit_event_policy": {
            "event_refs": [],
            "write_policy": "declared_only",
            "writes_audit_events_in_c09b": False,
        },
        "artifact_policy": {
            "artifact_refs_allowed": True,
            "writes_artifacts_in_c09b": False,
            "local_path_allowed": False,
            "external_reference_allowed": False,
            "safe_reference_only": True,
        },
        "callback_policy": {
            "callback_supported": False,
            "callback_connected_in_c09b": False,
            "correlation_id_policy": "declared_only_no_callback_delivery",
            "external_endpoint_declared": False,
        },
        "failure_policy": {
            "safe_error_code_required": True,
            "safe_error_message_required": True,
            "raw_provider_error_exposed": False,
            "retry_requires_policy_match": True,
        },
        "fallback_behavior": _fallback_behavior(),
        "unavailable_behavior": _unavailable_behavior(
            block_reason=unavailable_reason
        ),
        "test_contracts": [
            _test_contract(
                "c09b.execution_provider.contract",
                "Validate C09B provider contract shape and safe no-execute behavior.",
            )
        ],
        "docs_path": "docs/C09_EXECUTION_PROVIDER_BACKEND.md",
        "operation_log_action": operation_log_action,
        "requires_execution_provider": requires_execution_provider,
        "requires_approval": requires_approval,
        "executable": False,
        "can_request_execution": can_request_execution,
        "live_provider_connected": False,
        "external_endpoint_declared": False,
        "credential_declared": False,
    }


EXECUTION_PROVIDER_CONTRACTS_V1: tuple[dict[str, Any], ...] = (
    _provider(
        provider_key="core.no_op_provider",
        provider_type="no_op_provider",
        provider_status="mock",
        provider_readiness="mock",
        lifecycle="mock",
        display_name="Core No-op Execution Provider",
        description=(
            "No-op provider contract for an execution-required adapter action; "
            "it never runs business work in C09B."
        ),
        supported_execution_modes=("mock", "no_op", "contract_only"),
        supported_action_types=("prepare",),
        module_key="business.products",
        adapter_key="business.products.placeholder.adapter",
        action_key="business.products.placeholder.prepare",
        required_permission="products.read",
        risk_level="medium",
        operation_log_action="business.products.placeholder.prepare",
        requires_execution_provider=True,
        unavailable_reason="execution_provider_required_no_op_only",
        can_request_execution=True,
    ),
    _provider(
        provider_key="core.mock_provider",
        provider_type="mock_provider",
        provider_status="mock",
        provider_readiness="mock",
        lifecycle="mock",
        display_name="Core Mock Execution Provider",
        description=(
            "Mock provider contract for access-state and schema tests; it does "
            "not create execution requests."
        ),
        supported_execution_modes=("mock", "contract_only"),
        supported_action_types=("read",),
        module_key="admin.users",
        adapter_key="admin.users.adapter",
        action_key="admin.users.read",
        required_permission="users.read",
        risk_level="medium",
        operation_log_action="user.read",
        requires_scope=True,
        unavailable_reason="scope_adapter_pending",
    ),
    _provider(
        provider_key="core.contract_only_provider",
        provider_type="contract_only_provider",
        provider_status="mock",
        provider_readiness="mock",
        lifecycle="mock",
        display_name="Core Contract-only Execution Provider",
        description=(
            "Contract-only provider for approval-gated admin action metadata; "
            "C12 must exist before execution can be considered."
        ),
        supported_execution_modes=("contract_only",),
        supported_action_types=("manage",),
        module_key="admin.permissions",
        adapter_key="admin.permissions.adapter",
        action_key="admin.permissions.manage",
        required_permission="permissions.manage",
        risk_level="critical",
        operation_log_action="permission.assignment.manage",
        requires_approval=True,
        unavailable_reason="blocked_approval_required",
    ),
    _provider(
        provider_key="future.local_backend_provider",
        provider_type="local_backend_provider",
        provider_status="staging_ready",
        provider_readiness="staging_ready",
        lifecycle="staging_ready",
        display_name="Future Local Backend Execution Provider",
        description="Future local backend provider placeholder; disabled from execution in C09B.",
        supported_execution_modes=("staging", "local_backend"),
        supported_action_types=("read",),
        module_key="admin.users",
        adapter_key="admin.users.adapter",
        action_key="admin.users.read",
        required_permission="users.read",
        risk_level="medium",
        operation_log_action="user.read",
        unavailable_reason="provider_pending",
    ),
    _provider(
        provider_key="future.queue_provider",
        provider_type="queue_provider",
        provider_status="staging_ready",
        provider_readiness="staging_ready",
        lifecycle="staging_ready",
        display_name="Future Queue Execution Provider",
        description="Future queue provider placeholder; no queue is created in C09B.",
        supported_execution_modes=("staging", "queue"),
        supported_action_types=("prepare",),
        module_key="business.products",
        adapter_key="business.products.placeholder.adapter",
        action_key="business.products.placeholder.prepare",
        required_permission="products.read",
        risk_level="medium",
        operation_log_action="business.products.placeholder.prepare",
        requires_execution_provider=True,
        unavailable_reason="provider_pending",
        can_request_execution=True,
    ),
    _provider(
        provider_key="future.webhook_provider",
        provider_type="webhook_provider",
        provider_status="staging_ready",
        provider_readiness="staging_ready",
        lifecycle="staging_ready",
        display_name="Future Webhook Execution Provider",
        description="Future webhook provider placeholder; no callback or external endpoint is connected.",
        supported_execution_modes=("staging", "webhook"),
        supported_action_types=("declare",),
        module_key="integration.n8n_test_bridge",
        adapter_key="integration.n8n_test_bridge.adapter",
        action_key="integration.n8n_test_bridge.test_run.declare",
        required_permission="jobs.create",
        risk_level="medium",
        operation_log_action="n8n_test.run",
        requires_execution_provider=True,
        unavailable_reason="disabled",
        can_request_execution=True,
    ),
    _provider(
        provider_key="future.scheduled_provider",
        provider_type="scheduled_provider",
        provider_status="staging_ready",
        provider_readiness="staging_ready",
        lifecycle="staging_ready",
        display_name="Future Scheduled Execution Provider",
        description="Future scheduled provider placeholder; no scheduler is created in C09B.",
        supported_execution_modes=("staging", "scheduled"),
        supported_action_types=("manage",),
        module_key="admin.users",
        adapter_key="admin.users.adapter",
        action_key="admin.users.manage",
        required_permission="users.manage",
        risk_level="high",
        operation_log_action="user.manage",
        requires_approval=True,
        unavailable_reason="disabled",
    ),
    _provider(
        provider_key="future.live_provider",
        provider_type="future_live_provider",
        provider_status="live_ready",
        provider_readiness="live_ready",
        lifecycle="live_ready",
        display_name="Future Live Execution Provider",
        description="Future live provider placeholder; it is not connected and cannot execute in C09B.",
        supported_execution_modes=("live", "future_live"),
        supported_action_types=("declare",),
        module_key="integration.n8n_test_bridge",
        adapter_key="integration.n8n_test_bridge.adapter",
        action_key="integration.n8n_test_bridge.test_run.declare",
        required_permission="jobs.create",
        risk_level="medium",
        operation_log_action="n8n_test.run",
        requires_execution_provider=True,
        requires_secret=True,
        unavailable_reason="provider_pending",
    ),
)
