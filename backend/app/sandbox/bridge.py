from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..schemas.execution_provider import (
    ExecutionLifecycleStatus,
    ExecutionProviderType,
    ExecutionRequestContractV1,
    ExecutionResultContractV1,
    ExecutionRiskLevel,
)
from .context import SandboxContext, SandboxTrustBoundary
from .execution_context import ExecutionContext, ExecutionContextFactory
from .runner import SAFETY_GUARANTEES, SandboxRunner
from .types import SandboxRequest, SandboxResponse, SandboxTrustZone


BRIDGE_STAGE: Literal["c10e_execution_bridge"] = "c10e_execution_bridge"
PROVIDER_MOCK_INTERFACE_KEY = "c09.execution_provider.mock_interface.v1"
SandboxBridgeMode = Literal[
    "passthrough_mock_mode",
    "dry_run_mode",
    "simulation_mode",
]
BridgeStatus = Literal["mock_succeeded", "mock_blocked"]
ProviderForwardStatus = Literal[
    "mock_forward_accepted",
    "dry_run_accepted",
    "simulation_accepted",
    "mock_forward_rejected",
]

BRIDGE_FLOW = [
    "User Action",
    "C08 Module Adapter",
    "C09 Execution Provider",
    "C10 Sandbox Bridge",
    "C10 Sandbox Runner",
    "Mock result",
]
BRIDGE_SAFETY_GUARANTEES = [
    "Bridge accepts only ExecutionRequestContractV1 data.",
    "Bridge modes are mock-only: passthrough_mock_mode, dry_run_mode, simulation_mode.",
    "C09 provider forwarding targets an in-memory mock interface only.",
    "No live provider connector, queue, webhook, callback, or network client is selected.",
    "No runtime process, subprocess, container, worker, or shell command is created.",
    "No production or staging environment is read or mutated by the bridge.",
    "No database write, operation-log write, or audit-event write is performed.",
    "No filesystem access is performed by the bridge.",
    "Sandbox runner output is accepted only when it reports safe_result_only.",
]
VISIBLE_TRUST_ZONES: list[SandboxTrustZone] = [
    "user_action",
    "c08_module_adapter",
    "c09_execution_provider",
    "c10_sandbox",
]
UNSAFE_CAPABILITIES = frozenset(
    {
        "runtime_execution",
        "external_provider_call",
        "external_provider",
        "external_api",
        "external_api_call",
        "network",
        "network_access",
        "production_access",
        "staging_access",
        "db_write",
        "db_mutation",
        "filesystem_access",
        "filesystem_write",
        "filesystem_write_outside_sandbox",
        "host_filesystem_access",
        "subprocess",
        "docker",
    }
)


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _shape(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {
            "type": "object",
            "key_count": len(value),
            "keys_redacted": True,
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "item_count": len(value),
            "item_types": sorted({type(item).__name__ for item in value}),
        }
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def _execution_request_from_raw(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
) -> ExecutionRequestContractV1:
    if isinstance(execution_request, ExecutionRequestContractV1):
        return execution_request
    return ExecutionRequestContractV1.model_validate(execution_request)


def _enforce_execution_flow_gate(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
) -> None:
    from ..services.execution_flow_gate import C13E_GATE

    C13E_GATE.check(
        execution_request,
        integration_point="c10_sandbox_entry",
    )


class BridgeSafetyViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=300)
    blocked: bool = True


class BridgeSafetyGuardReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    guard_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10e_execution_bridge"] = BRIDGE_STAGE
    bridge_mode: SandboxBridgeMode
    safe: bool
    violations: tuple[BridgeSafetyViolation, ...] = Field(default_factory=tuple)
    no_real_execution: Literal[True] = True
    runtime_created: Literal[False] = False
    no_external_provider_call: Literal[True] = True
    external_provider_called: Literal[False] = False
    live_provider_called: Literal[False] = False
    network_access_performed: Literal[False] = False
    production_access_performed: Literal[False] = False
    production_mutated: Literal[False] = False
    staging_access_performed: Literal[False] = False
    staging_mutated: Literal[False] = False
    db_write_performed: Literal[False] = False
    operation_log_write_performed: Literal[False] = False
    audit_event_write_performed: Literal[False] = False
    filesystem_access_performed: Literal[False] = False
    filesystem_write_performed: Literal[False] = False
    subprocess_started: Literal[False] = False
    docker_started: Literal[False] = False
    safe_result_only: Literal[True] = True


class ProviderRequestMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["provider_request_mapping"] = "provider_request_mapping"
    mapping_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10e_execution_bridge"] = BRIDGE_STAGE
    bridge_mode: SandboxBridgeMode
    provider_interface_key: Literal[
        "c09.execution_provider.mock_interface.v1"
    ] = PROVIDER_MOCK_INTERFACE_KEY
    provider_key: str = Field(min_length=1, max_length=180)
    provider_type: ExecutionProviderType
    execution_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    source_schema: Literal["ExecutionRequestContractV1"] = (
        "ExecutionRequestContractV1"
    )
    target_schema: Literal["C09MockExecutionProviderInterface"] = (
        "C09MockExecutionProviderInterface"
    )
    field_mapping: dict[str, str]
    mock_interface_only: Literal[True] = True
    passthrough_contract_only: Literal[True] = True
    live_provider_call_allowed: Literal[False] = False
    external_provider_call_allowed: Literal[False] = False
    external_api_allowed: Literal[False] = False
    network_access_allowed: Literal[False] = False
    db_write_allowed: Literal[False] = False
    filesystem_access_allowed: Literal[False] = False
    production_access_allowed: Literal[False] = False
    staging_access_allowed: Literal[False] = False
    raw_input_payload_forwarded_to_provider: Literal[False] = False
    sanitized_summary_forwarded: Literal[True] = True


class SandboxRequestMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["sandbox_request_mapping"] = "sandbox_request_mapping"
    mapping_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10e_execution_bridge"] = BRIDGE_STAGE
    bridge_mode: SandboxBridgeMode
    source_schema: Literal["ExecutionRequestContractV1"] = (
        "ExecutionRequestContractV1"
    )
    target_schema: Literal["SandboxRequest"] = "SandboxRequest"
    sandbox_request_id: str | None = Field(default=None, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    context_id: str = Field(min_length=1, max_length=128)
    execution_context_ref: str = Field(min_length=1, max_length=180)
    scope_ref: str = Field(min_length=1, max_length=180)
    memory_scope_ref: str = Field(min_length=1, max_length=180)
    log_scope_ref: str = Field(min_length=1, max_length=180)
    state_scope_ref: str = Field(min_length=1, max_length=180)
    sandbox_scope_ref: str = Field(min_length=1, max_length=180)
    field_mapping: dict[str, str]
    context_bound: Literal[True] = True
    resource_control_delegated_to_c10d: Literal[True] = True
    raw_input_payload_persisted: Literal[False] = False
    raw_input_payload_echoed: Literal[False] = False
    safe_result_only: Literal[True] = True
    runtime_execution_allowed: Literal[False] = False
    external_provider_call_allowed: Literal[False] = False
    db_write_allowed: Literal[False] = False
    filesystem_access_allowed: Literal[False] = False
    production_access_allowed: Literal[False] = False
    staging_access_allowed: Literal[False] = False


class BridgeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["bridge_request"] = "bridge_request"
    bridge_request_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10e_execution_bridge"] = BRIDGE_STAGE
    bridge_mode: SandboxBridgeMode
    source_trust_zone: Literal["c09_execution_provider"] = "c09_execution_provider"
    target_trust_zone: Literal["c10_sandbox"] = "c10_sandbox"
    execution_request: ExecutionRequestContractV1
    execution_context: ExecutionContext
    sandbox_request: SandboxRequest
    provider_request_mapping: ProviderRequestMapping
    sandbox_request_mapping: SandboxRequestMapping
    safety_guard: BridgeSafetyGuardReport
    flow: list[str] = Field(default_factory=lambda: list(BRIDGE_FLOW))
    mock_only: Literal[True] = True
    safe_result_only: Literal[True] = True
    live_provider_call_allowed: Literal[False] = False
    external_provider_call_allowed: Literal[False] = False
    runtime_execution_allowed: Literal[False] = False
    db_write_allowed: Literal[False] = False
    filesystem_access_allowed: Literal[False] = False
    production_access_allowed: Literal[False] = False
    staging_access_allowed: Literal[False] = False


class C09MockProviderForwardRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["c09_mock_provider_forward_request"] = (
        "c09_mock_provider_forward_request"
    )
    forward_request_id: str = Field(min_length=1, max_length=180)
    bridge_request_id: str = Field(min_length=1, max_length=180)
    provider_request_mapping_id: str = Field(min_length=1, max_length=180)
    provider_interface_key: Literal[
        "c09.execution_provider.mock_interface.v1"
    ] = PROVIDER_MOCK_INTERFACE_KEY
    bridge_mode: SandboxBridgeMode
    provider_key: str = Field(min_length=1, max_length=180)
    provider_type: ExecutionProviderType
    execution_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    module_key: str = Field(min_length=1, max_length=128)
    adapter_key: str = Field(min_length=1, max_length=180)
    action_key: str = Field(min_length=1, max_length=180)
    actor_user_id: int | None = None
    status: ExecutionLifecycleStatus
    risk_level: ExecutionRiskLevel
    required_permission: str = Field(min_length=1, max_length=255)
    sanitized_input_summary: dict[str, Any] = Field(default_factory=dict)
    target_scope_shape: dict[str, Any] = Field(default_factory=dict)
    safety_guard_safe: bool
    mock_interface_only: Literal[True] = True
    raw_input_payload_included: Literal[False] = False
    raw_input_payload_echoed: Literal[False] = False
    live_provider_call_allowed: Literal[False] = False
    external_provider_call_allowed: Literal[False] = False
    network_access_allowed: Literal[False] = False
    db_write_allowed: Literal[False] = False
    filesystem_access_allowed: Literal[False] = False
    production_access_allowed: Literal[False] = False
    staging_access_allowed: Literal[False] = False


class C09MockProviderForwardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    response_id: str = Field(min_length=1, max_length=180)
    provider_interface_key: Literal[
        "c09.execution_provider.mock_interface.v1"
    ] = PROVIDER_MOCK_INTERFACE_KEY
    bridge_request_id: str = Field(min_length=1, max_length=180)
    provider_key: str = Field(min_length=1, max_length=180)
    provider_type: ExecutionProviderType
    bridge_mode: SandboxBridgeMode
    status: ProviderForwardStatus
    execution_status: ExecutionLifecycleStatus
    accepted: bool
    mock_interface_only: Literal[True] = True
    external_provider_called: Literal[False] = False
    live_provider_called: Literal[False] = False
    network_access_performed: Literal[False] = False
    db_write_performed: Literal[False] = False
    filesystem_access_performed: Literal[False] = False
    production_mutated: Literal[False] = False
    staging_mutated: Literal[False] = False
    result_contract_created: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class BridgeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["bridge_response"] = "bridge_response"
    bridge_response_id: str = Field(min_length=1, max_length=180)
    bridge_request_id: str = Field(min_length=1, max_length=180)
    stage: Literal["c10e_execution_bridge"] = BRIDGE_STAGE
    bridge_mode: SandboxBridgeMode
    status: BridgeStatus
    execution_status: ExecutionLifecycleStatus
    provider_request_mapping: ProviderRequestMapping
    sandbox_request_mapping: SandboxRequestMapping
    provider_forward_request: C09MockProviderForwardRequest
    provider_forward_response: C09MockProviderForwardResponse
    sandbox_response: SandboxResponse
    c09_result_contract: ExecutionResultContractV1 | None = None
    execution_context: ExecutionContext | None = None
    safety_guard: BridgeSafetyGuardReport
    flow: list[str] = Field(default_factory=lambda: list(BRIDGE_FLOW))
    safety_notes: list[str] = Field(default_factory=list)
    next_stage_policy: Literal["wait_for_c10f"] = "wait_for_c10f"
    safe_result_only: Literal[True] = True
    runtime_created: Literal[False] = False
    external_provider_called: Literal[False] = False
    live_provider_called: Literal[False] = False
    network_access_performed: Literal[False] = False
    db_write_performed: Literal[False] = False
    filesystem_access_performed: Literal[False] = False
    production_mutated: Literal[False] = False
    staging_mutated: Literal[False] = False


class C09MockExecutionProviderInterface:
    """In-memory C09 provider mock interface for C10E.

    The interface records a contract-level forward from C10E back to the C09
    provider boundary. It never selects or invokes a live provider connector.
    """

    def __init__(
        self,
        *,
        interface_key: str = PROVIDER_MOCK_INTERFACE_KEY,
    ) -> None:
        self.interface_key = interface_key

    def forward_request(
        self,
        provider_request: C09MockProviderForwardRequest | Mapping[str, Any],
    ) -> C09MockProviderForwardResponse:
        request = self._provider_request_from_raw(provider_request)
        accepted = request.safety_guard_safe
        return C09MockProviderForwardResponse(
            response_id=_stable_id(
                "provider_forward_resp",
                {
                    "interface_key": self.interface_key,
                    "bridge_request_id": request.bridge_request_id,
                    "forward_request_id": request.forward_request_id,
                    "provider_mapping_id": request.provider_request_mapping_id,
                    "accepted": accepted,
                    "bridge_mode": request.bridge_mode,
                },
            ),
            bridge_request_id=request.bridge_request_id,
            provider_key=request.provider_key,
            provider_type=request.provider_type,
            bridge_mode=request.bridge_mode,
            status=self._forward_status(request.bridge_mode, accepted=accepted),
            execution_status="accepted" if accepted else "rejected",
            accepted=accepted,
            notes=[
                "C09 provider mock interface received bridge contract only.",
                "No live provider, queue, webhook, callback, or network call was made.",
            ],
        )

    def receive_bridge_request(
        self,
        provider_request: C09MockProviderForwardRequest | Mapping[str, Any],
    ) -> C09MockProviderForwardResponse:
        return self.forward_request(provider_request)

    def _provider_request_from_raw(
        self,
        provider_request: C09MockProviderForwardRequest | Mapping[str, Any],
    ) -> C09MockProviderForwardRequest:
        if isinstance(provider_request, C09MockProviderForwardRequest):
            return provider_request
        return C09MockProviderForwardRequest.model_validate(provider_request)

    def _forward_status(
        self,
        bridge_mode: SandboxBridgeMode,
        *,
        accepted: bool,
    ) -> ProviderForwardStatus:
        if not accepted:
            return "mock_forward_rejected"
        if bridge_mode == "dry_run_mode":
            return "dry_run_accepted"
        if bridge_mode == "simulation_mode":
            return "simulation_accepted"
        return "mock_forward_accepted"


class SandboxExecutionBridge:
    """C10E bridge between C09 execution contracts and C10 mock sandbox.

    The bridge binds an isolated C10C execution context, maps the C09 request
    into a C10 sandbox request, forwards a contract-only copy to the C09 mock
    provider interface, then delegates to the C10B runner for deterministic
    mock output. It does not execute provider work.
    """

    def __init__(
        self,
        *,
        bridge_key: str = "c10e.sandbox_execution_bridge.v1",
        bridge_version: str = "1.0.0",
        context_factory: ExecutionContextFactory | None = None,
        runner: SandboxRunner | None = None,
        provider_interface: C09MockExecutionProviderInterface | None = None,
    ) -> None:
        self.bridge_key = bridge_key
        self.bridge_version = bridge_version
        self.context_factory = context_factory or ExecutionContextFactory()
        self.runner = runner or SandboxRunner(
            context_factory=self.context_factory,
        )
        self.provider_interface = (
            provider_interface or C09MockExecutionProviderInterface()
        )

    def receive_execution_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> BridgeResponse:
        bridge_request = self.build_bridge_request(
            execution_request,
            bridge_mode=bridge_mode,
            context=context,
        )
        provider_forward_request = self.build_provider_forward_request(
            bridge_request
        )
        provider_forward_response = self.provider_interface.forward_request(
            provider_forward_request
        )
        sandbox_context = self._sandbox_context_from_bridge_request(bridge_request)
        sandbox_response = self.runner.run(
            bridge_request.sandbox_request,
            context=sandbox_context,
            execution_context=bridge_request.execution_context,
        )
        safety_guard = self._build_safety_guard(
            bridge_mode=bridge_request.bridge_mode,
            execution_request=bridge_request.execution_request,
            execution_context=sandbox_response.execution_context
            or bridge_request.execution_context,
            sandbox_request=bridge_request.sandbox_request,
            provider_forward_response=provider_forward_response,
            sandbox_response=sandbox_response,
        )
        status: BridgeStatus = (
            "mock_succeeded"
            if safety_guard.safe
            and sandbox_response.result.status != "mock_blocked"
            else "mock_blocked"
        )
        return BridgeResponse(
            bridge_response_id=_stable_id(
                "bridge_resp",
                {
                    "bridge_key": self.bridge_key,
                    "bridge_request_id": bridge_request.bridge_request_id,
                    "provider_forward_response_id": (
                        provider_forward_response.response_id
                    ),
                    "sandbox_response_id": sandbox_response.response_id,
                    "safe": safety_guard.safe,
                },
            ),
            bridge_request_id=bridge_request.bridge_request_id,
            bridge_mode=bridge_request.bridge_mode,
            status=status,
            execution_status=sandbox_response.result.execution_status,
            provider_request_mapping=bridge_request.provider_request_mapping,
            sandbox_request_mapping=bridge_request.sandbox_request_mapping,
            provider_forward_request=provider_forward_request,
            provider_forward_response=provider_forward_response,
            sandbox_response=sandbox_response,
            c09_result_contract=sandbox_response.c09_result_contract,
            execution_context=sandbox_response.execution_context,
            safety_guard=safety_guard,
            safety_notes=[
                *BRIDGE_SAFETY_GUARANTEES,
                *sandbox_response.safety_notes,
            ],
        )

    def handle_execution_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> BridgeResponse:
        return self.receive_execution_request(
            execution_request,
            bridge_mode=bridge_mode,
            context=context,
        )

    def build_bridge_request(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
        context: ExecutionContext | None = None,
    ) -> BridgeRequest:
        request_contract = _execution_request_from_raw(execution_request)
        _enforce_execution_flow_gate(request_contract)
        execution_context = context or self.context_factory.create_context(
            request_contract
        )
        sandbox_context = self._sandbox_context_from_execution_request(
            request_contract,
            execution_context=execution_context,
            bridge_mode=bridge_mode,
        )
        sandbox_request = self.runner.build_sandbox_request(
            request_contract,
            context=sandbox_context,
            execution_context=execution_context,
            requested_capabilities=self._requested_capabilities_for_mode(
                bridge_mode
            ),
        ).model_copy(
            update={
                "stage": BRIDGE_STAGE,
                "contract_mode": "mock_only",
                "source_trust_zone": "c09_execution_provider",
                "target_trust_zone": "c10_sandbox",
            }
        )
        provider_mapping = self.build_provider_request_mapping(
            request_contract,
            execution_context=execution_context,
            bridge_mode=bridge_mode,
        )
        sandbox_mapping = self.build_sandbox_request_mapping(
            request_contract,
            sandbox_request=sandbox_request,
            execution_context=execution_context,
            bridge_mode=bridge_mode,
        )
        safety_guard = self._build_safety_guard(
            bridge_mode=bridge_mode,
            execution_request=request_contract,
            execution_context=execution_context,
            sandbox_request=sandbox_request,
        )
        bridge_request_id = _stable_id(
            "bridge_req",
            {
                "bridge_key": self.bridge_key,
                "bridge_version": self.bridge_version,
                "execution_request": request_contract.model_dump(mode="json"),
                "execution_context_ref": (
                    execution_context.execution_context_ref
                ),
                "sandbox_request_id": sandbox_request.sandbox_request_id,
                "bridge_mode": bridge_mode,
            },
        )
        return BridgeRequest(
            bridge_request_id=bridge_request_id,
            bridge_mode=bridge_mode,
            execution_request=request_contract,
            execution_context=execution_context,
            sandbox_request=sandbox_request,
            provider_request_mapping=provider_mapping,
            sandbox_request_mapping=sandbox_mapping,
            safety_guard=safety_guard,
        )

    def build_provider_forward_request(
        self,
        bridge_request: BridgeRequest,
    ) -> C09MockProviderForwardRequest:
        execution_request = bridge_request.execution_request
        safe_summary = self._safe_input_summary(execution_request)
        return C09MockProviderForwardRequest(
            forward_request_id=_stable_id(
                "provider_forward_req",
                {
                    "bridge_key": self.bridge_key,
                    "bridge_request_id": bridge_request.bridge_request_id,
                    "provider_mapping_id": (
                        bridge_request.provider_request_mapping.mapping_id
                    ),
                    "bridge_mode": bridge_request.bridge_mode,
                    "request_id": execution_request.request_id,
                    "execution_id": execution_request.execution_id,
                    "safe_summary": safe_summary,
                },
            ),
            bridge_request_id=bridge_request.bridge_request_id,
            provider_request_mapping_id=(
                bridge_request.provider_request_mapping.mapping_id
            ),
            bridge_mode=bridge_request.bridge_mode,
            provider_key=execution_request.provider_key,
            provider_type=execution_request.provider_type,
            execution_id=bridge_request.execution_context.execution_id,
            request_id=execution_request.request_id,
            module_key=execution_request.module_key,
            adapter_key=execution_request.adapter_key,
            action_key=execution_request.action_key,
            actor_user_id=execution_request.actor_user_id,
            status=execution_request.status,
            risk_level=execution_request.risk_level,
            required_permission=execution_request.required_permission,
            sanitized_input_summary=safe_summary,
            target_scope_shape=_shape(execution_request.target_scope),
            safety_guard_safe=bridge_request.safety_guard.safe,
        )

    def build_provider_request_mapping(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        execution_context: ExecutionContext,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
    ) -> ProviderRequestMapping:
        request_contract = _execution_request_from_raw(execution_request)
        _enforce_execution_flow_gate(request_contract)
        mapping_fields = {
            "execution_id": "execution_id",
            "request_id": "request_id",
            "module_key": "module_key",
            "adapter_key": "adapter_key",
            "action_key": "action_key",
            "actor_user_id": "actor_user_id",
            "provider_key": "provider_key",
            "provider_type": "provider_type",
            "status": "status",
            "risk_level": "risk_level",
            "required_permission": "required_permission",
            "sanitized_input_summary": "sanitized_input_summary",
        }
        return ProviderRequestMapping(
            mapping_id=_stable_id(
                "provider_mapping",
                {
                    "bridge_key": self.bridge_key,
                    "provider_key": request_contract.provider_key,
                    "provider_type": request_contract.provider_type,
                    "execution_context_ref": (
                        execution_context.execution_context_ref
                    ),
                    "bridge_mode": bridge_mode,
                    "field_mapping": mapping_fields,
                },
            ),
            bridge_mode=bridge_mode,
            provider_key=request_contract.provider_key,
            provider_type=request_contract.provider_type,
            execution_id=execution_context.execution_id,
            request_id=request_contract.request_id,
            field_mapping=mapping_fields,
        )

    def build_sandbox_request_mapping(
        self,
        execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
        *,
        sandbox_request: SandboxRequest,
        execution_context: ExecutionContext,
        bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
    ) -> SandboxRequestMapping:
        request_contract = _execution_request_from_raw(execution_request)
        _enforce_execution_flow_gate(request_contract)
        mapping_fields = {
            "execution_id": "c09_execution_request.execution_id",
            "request_id": "request_id",
            "module_key": "module_key",
            "adapter_key": "adapter_key",
            "provider_key": "provider_key",
            "provider_type": "provider_type",
            "action_key": "action_key",
            "actor_user_id": "actor_user_id",
            "target_scope": "target_scope",
            "risk_level": "risk_level",
            "sanitized_input_summary": "sanitized_input_summary",
            "execution_context_ref": "execution_context_ref",
            "scope_ref": "scope_ref",
            "sandbox_scope_ref": "sandbox_scope_ref",
        }
        return SandboxRequestMapping(
            mapping_id=_stable_id(
                "sandbox_mapping",
                {
                    "bridge_key": self.bridge_key,
                    "sandbox_request_id": sandbox_request.sandbox_request_id,
                    "execution_context_ref": (
                        execution_context.execution_context_ref
                    ),
                    "request": request_contract.model_dump(mode="json"),
                    "bridge_mode": bridge_mode,
                    "field_mapping": mapping_fields,
                },
            ),
            bridge_mode=bridge_mode,
            sandbox_request_id=sandbox_request.sandbox_request_id,
            execution_id=execution_context.execution_id,
            context_id=execution_context.context_id,
            execution_context_ref=execution_context.execution_context_ref,
            scope_ref=execution_context.scope_ref,
            memory_scope_ref=execution_context.memory_scope.memory_scope_id,
            log_scope_ref=execution_context.log_scope.log_scope_id,
            state_scope_ref=execution_context.state_scope.state_scope_id,
            sandbox_scope_ref=execution_context.sandbox_scope_ref,
            field_mapping=mapping_fields,
        )

    def _sandbox_context_from_execution_request(
        self,
        execution_request: ExecutionRequestContractV1,
        *,
        execution_context: ExecutionContext,
        bridge_mode: SandboxBridgeMode,
    ) -> SandboxContext:
        boundary_key = _stable_id(
            "bridge_boundary",
            {
                "bridge_key": self.bridge_key,
                "execution_id": execution_context.execution_id,
                "context_id": execution_context.context_id,
                "bridge_mode": bridge_mode,
            },
        )
        return SandboxContext(
            context_id=execution_context.context_id,
            stage=BRIDGE_STAGE,
            module_key=execution_request.module_key,
            adapter_key=execution_request.adapter_key,
            provider_key=execution_request.provider_key,
            action_key=execution_request.action_key,
            actor_user_id=execution_request.actor_user_id,
            risk_level=execution_request.risk_level,
            trust_boundary=SandboxTrustBoundary(boundary_key=boundary_key),
            execution_context_ref=execution_context.execution_context_ref,
            sandbox_scope_ref=execution_context.sandbox_scope_ref,
            resource_policy_ref=execution_context.resource_policy_ref,
            resource_policy=execution_context.resource_policy,
            request_metadata={
                "bridge_key": self.bridge_key,
                "bridge_version": self.bridge_version,
                "bridge_stage": BRIDGE_STAGE,
                "bridge_mode": bridge_mode,
                "c10c_stage": execution_context.stage,
                "c10c_context_id": execution_context.context_id,
                "scope_ref": execution_context.scope_ref,
                "memory_scope_ref": execution_context.memory_scope.memory_scope_id,
                "log_scope_ref": execution_context.log_scope.log_scope_id,
                "state_scope_ref": execution_context.state_scope.state_scope_id,
                "provider_mock_interface_key": PROVIDER_MOCK_INTERFACE_KEY,
                "mock_only": True,
                "raw_input_payload_echoed": False,
                "external_provider_called": False,
            },
            sanitized_input_summary=self._safe_input_summary(execution_request),
            visible_trust_zones=list(VISIBLE_TRUST_ZONES),
            runtime_execution_policy="mock_simulation_only",
        )

    def _sandbox_context_from_bridge_request(
        self,
        bridge_request: BridgeRequest,
    ) -> SandboxContext:
        return self._sandbox_context_from_execution_request(
            bridge_request.execution_request,
            execution_context=bridge_request.execution_context,
            bridge_mode=bridge_request.bridge_mode,
        )

    def _requested_capabilities_for_mode(
        self,
        bridge_mode: SandboxBridgeMode,
    ) -> list[str]:
        capabilities = [
            "bridge_contract_mapping",
            "provider_mock_interface_forward",
        ]
        if bridge_mode == "dry_run_mode":
            capabilities.append("dry_run_contract_validation")
        elif bridge_mode == "simulation_mode":
            capabilities.append("deterministic_mock_simulation")
        else:
            capabilities.append("passthrough_mock_contract")
        return capabilities

    def _safe_input_summary(
        self,
        execution_request: ExecutionRequestContractV1,
    ) -> dict[str, Any]:
        return {
            "provided_summary": execution_request.sanitized_input_summary,
            "input_payload_shape": _shape(execution_request.input_payload),
            "target_scope_shape": _shape(execution_request.target_scope),
            "raw_input_payload_echoed": False,
        }

    def _build_safety_guard(
        self,
        *,
        bridge_mode: SandboxBridgeMode,
        execution_request: ExecutionRequestContractV1,
        execution_context: ExecutionContext,
        sandbox_request: SandboxRequest,
        provider_forward_response: (
            C09MockProviderForwardResponse | None
        ) = None,
        sandbox_response: SandboxResponse | None = None,
    ) -> BridgeSafetyGuardReport:
        violations: list[BridgeSafetyViolation] = []

        def add_violation(code: str, message: str) -> None:
            violations.append(
                BridgeSafetyViolation(
                    code=code,
                    message=message,
                    blocked=True,
                )
            )

        if execution_context.runtime_execution_allowed:
            add_violation(
                "C10E_RUNTIME_ALLOWED",
                "Execution context cannot allow runtime execution.",
            )
        if execution_context.external_provider_call_allowed:
            add_violation(
                "C10E_PROVIDER_CALL_ALLOWED",
                "Execution context cannot allow external provider calls.",
            )
        if execution_context.db_mutation_allowed:
            add_violation(
                "C10E_DB_MUTATION_ALLOWED",
                "Execution context cannot allow database mutation.",
            )
        if execution_context.filesystem_write_allowed:
            add_violation(
                "C10E_FILESYSTEM_WRITE_ALLOWED",
                "Execution context cannot allow filesystem writes.",
            )
        if (
            execution_context.production_access_allowed
            or execution_context.staging_access_allowed
        ):
            add_violation(
                "C10E_ENV_ACCESS_ALLOWED",
                "Execution context cannot allow production or staging access.",
            )

        unsafe_capabilities = sorted(
            set(sandbox_request.requested_capabilities).intersection(
                UNSAFE_CAPABILITIES
            )
        )
        if unsafe_capabilities:
            add_violation(
                "C10E_UNSAFE_CAPABILITY_REQUESTED",
                "Bridge request contains unsafe capabilities: "
                + ", ".join(unsafe_capabilities),
            )

        if sandbox_request.production_access_policy != "denied":
            add_violation(
                "C10E_PRODUCTION_POLICY_OPEN",
                "Sandbox request production policy must remain denied.",
            )
        if sandbox_request.external_provider_policy != "denied":
            add_violation(
                "C10E_EXTERNAL_PROVIDER_POLICY_OPEN",
                "Sandbox request external provider policy must remain denied.",
            )
        if sandbox_request.db_mutation_policy != "denied":
            add_violation(
                "C10E_DB_POLICY_OPEN",
                "Sandbox request database mutation policy must remain denied.",
            )

        if provider_forward_response is not None:
            if provider_forward_response.external_provider_called:
                add_violation(
                    "C10E_PROVIDER_FORWARD_ESCAPED",
                    "Provider mock interface reported an external provider call.",
                )
            if provider_forward_response.live_provider_called:
                add_violation(
                    "C10E_LIVE_PROVIDER_CALLED",
                    "Provider mock interface reported a live provider call.",
                )
            if provider_forward_response.network_access_performed:
                add_violation(
                    "C10E_PROVIDER_NETWORK_ACCESS",
                    "Provider mock interface reported network access.",
                )
            if provider_forward_response.db_write_performed:
                add_violation(
                    "C10E_PROVIDER_DB_WRITE",
                    "Provider mock interface reported a database write.",
                )
            if provider_forward_response.filesystem_access_performed:
                add_violation(
                    "C10E_PROVIDER_FILESYSTEM_ACCESS",
                    "Provider mock interface reported filesystem access.",
                )
            if (
                provider_forward_response.production_mutated
                or provider_forward_response.staging_mutated
            ):
                add_violation(
                    "C10E_PROVIDER_ENV_MUTATION",
                    "Provider mock interface reported environment mutation.",
                )

        if sandbox_response is not None:
            result = sandbox_response.result
            if result.runtime_created:
                add_violation(
                    "C10E_RUNNER_RUNTIME_CREATED",
                    "Sandbox runner reported runtime creation.",
                )
            if result.external_provider_called:
                add_violation(
                    "C10E_RUNNER_PROVIDER_CALLED",
                    "Sandbox runner reported external provider call.",
                )
            if result.db_mutated:
                add_violation(
                    "C10E_RUNNER_DB_MUTATED",
                    "Sandbox runner reported database mutation.",
                )
            if result.production_touched or result.staging_touched:
                add_violation(
                    "C10E_RUNNER_ENV_TOUCHED",
                    "Sandbox runner reported production or staging touch.",
                )
            if result.filesystem_write_scope != "none":
                add_violation(
                    "C10E_RUNNER_FILESYSTEM_WRITE",
                    "Sandbox runner reported filesystem writes.",
                )
            if result.safe_result_only is not True:
                add_violation(
                    "C10E_UNSAFE_RESULT",
                    "Sandbox runner result must be safe-result-only.",
                )
            if (
                sandbox_response.c09_result_contract is not None
                and sandbox_response.c09_result_contract.safe_result_only
                is not True
            ):
                add_violation(
                    "C10E_UNSAFE_C09_RESULT",
                    "C09 result contract must be safe-result-only.",
                )

        return BridgeSafetyGuardReport(
            guard_id=_stable_id(
                "bridge_guard",
                {
                    "bridge_key": self.bridge_key,
                    "bridge_mode": bridge_mode,
                    "request": execution_request.model_dump(mode="json"),
                    "context_id": execution_context.context_id,
                    "sandbox_request_id": sandbox_request.sandbox_request_id,
                    "provider_forward_response_id": (
                        provider_forward_response.response_id
                        if provider_forward_response
                        else None
                    ),
                    "sandbox_response_id": (
                        sandbox_response.response_id if sandbox_response else None
                    ),
                    "violations": [
                        violation.model_dump(mode="json")
                        for violation in violations
                    ],
                },
            ),
            bridge_mode=bridge_mode,
            safe=not violations,
            violations=tuple(violations),
        )


def bridge_execution_request(
    execution_request: ExecutionRequestContractV1 | Mapping[str, Any],
    *,
    bridge_mode: SandboxBridgeMode = "passthrough_mock_mode",
    context: ExecutionContext | None = None,
) -> BridgeResponse:
    return SandboxExecutionBridge().receive_execution_request(
        execution_request,
        bridge_mode=bridge_mode,
        context=context,
    )


__all__ = [
    "BRIDGE_FLOW",
    "BRIDGE_SAFETY_GUARANTEES",
    "BRIDGE_STAGE",
    "PROVIDER_MOCK_INTERFACE_KEY",
    "BridgeRequest",
    "BridgeResponse",
    "BridgeSafetyGuardReport",
    "BridgeSafetyViolation",
    "BridgeStatus",
    "C09MockExecutionProviderInterface",
    "C09MockProviderForwardRequest",
    "C09MockProviderForwardResponse",
    "ProviderForwardStatus",
    "ProviderRequestMapping",
    "SandboxBridgeMode",
    "SandboxExecutionBridge",
    "SandboxRequestMapping",
    "bridge_execution_request",
]
