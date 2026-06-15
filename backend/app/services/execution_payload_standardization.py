from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from ..schemas.ai_execution_binding import AIExecutionBindingRecord
from ..schemas.capability_binding import (
    CapabilityBindingRecord,
    ModuleCapabilityBindingRecord,
)
from ..schemas.common import reject_sensitive_data
from ..schemas.execution_payload_standardization import (
    ExecutionPayloadCompletionStatus,
    ExecutionPayloadContextRules,
    ExecutionPayloadMetadata,
    ExecutionPayloadNormalizationEngineDesign,
    ExecutionPayloadNormalizationResult,
    ExecutionPayloadStandardRequest,
    ExecutionPayloadStandardizationModel,
    ExecutionPayloadTraceChain,
    ExecutionPayloadWorkflowMappingIntegration,
    reject_runtime_payload_data,
)
from ..schemas.model_lock import ModelLockRegistryRecord
from ..schemas.workflow_registry import (
    WorkflowInvocationDecision,
    WorkflowRegistryRecord,
)
from .capability_binding_engine import (
    build_capability_routing_model,
    validate_capability_binding_request,
)
from .module_registry import MODULE_KEY_PATTERN, get_module_manifest
from .workflow_registry_system import (
    evaluate_workflow_invocation,
    list_workflows_for_module,
)


CONTEXT_ID_PATTERN = re.compile(r"^ctx\.c15c\.[0-9a-f]{16}$")
MODULE_ALIASES = ("module", "module_key")
TASK_ALIASES = ("task", "action", "operation")
CONTEXT_ALIASES = (
    "context_id",
    "contextId",
    "correlation_id",
    "trace_id",
    "context",
)
ROUTING_FIELD_ALIASES = frozenset(
    MODULE_ALIASES
    + TASK_ALIASES
    + CONTEXT_ALIASES
    + ("payload", "timestamp", "workflow_id")
)
CALLER_EXECUTION_METADATA_KEYS = frozenset(
    ("execution", "capability", "model", "key", "key_id")
)
BLOCKED_REQUEST_VALUE_MARKERS = (
    "http://",
    "https://",
    "authorization:",
    "bearer ",
    "credential=",
    "password=",
    "secret=",
    "token=",
)


def _utc_now_timestamp() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: str) -> None:
    datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _extract_alias(
    raw: Mapping[str, Any],
    aliases: Sequence[str],
) -> Any:
    for alias in aliases:
        if alias in raw and raw[alias] is not None:
            return raw[alias]
    return None


def _contains_blocked_value_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in BLOCKED_REQUEST_VALUE_MARKERS)


def _validate_safe_string(value: str, field_name: str) -> None:
    if _contains_blocked_value_marker(value):
        raise ValueError(
            f"C15C {field_name} contains blocked runtime or credential data."
        )


def _validate_module(module: str) -> None:
    if not MODULE_KEY_PATTERN.fullmatch(module):
        raise ValueError("C15C module must use a registered module key.")
    if get_module_manifest(module) is None:
        raise ValueError(f"C15C module is not registered: {module}")


def _required_string_alias(
    raw: Mapping[str, Any],
    aliases: Sequence[str],
    field_name: str,
) -> str:
    value = _string_value(_extract_alias(raw, aliases))
    if value is None:
        raise ValueError(f"C15C {field_name} is required.")
    _validate_safe_string(value, field_name)
    return value


def _timestamp_from_request(raw: Mapping[str, Any]) -> str:
    value = _string_value(raw.get("timestamp"))
    if value is None:
        return _utc_now_timestamp()
    _parse_timestamp(value)
    return value


def _reject_caller_execution_metadata(raw: Mapping[str, Any]) -> None:
    present = CALLER_EXECUTION_METADATA_KEYS.intersection(raw)
    if present:
        keys = ", ".join(sorted(present))
        raise ValueError(
            "C15C execution metadata must be attached from C14X, not from "
            f"caller fields: {keys}."
        )


def _extract_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    if "payload" in raw:
        payload = raw["payload"]
        if not isinstance(payload, Mapping):
            raise ValueError("C15C payload must be a JSON object.")
        normalized_payload = dict(payload)
        reject_sensitive_data(normalized_payload)
        reject_runtime_payload_data(normalized_payload)
        return normalized_payload

    normalized_payload = {
        str(key): value
        for key, value in raw.items()
        if key not in ROUTING_FIELD_ALIASES
        and key not in CALLER_EXECUTION_METADATA_KEYS
    }
    reject_sensitive_data(normalized_payload)
    reject_runtime_payload_data(normalized_payload)
    return normalized_payload


def standardize_context_id(
    *,
    module: str,
    task: str,
    raw_context: Any,
    timestamp: str,
) -> str:
    raw_value = _string_value(raw_context)
    if raw_value and CONTEXT_ID_PATTERN.fullmatch(raw_value):
        return raw_value

    digest_source = {
        "module": module,
        "task": task,
        "raw_context": raw_context,
        "timestamp": timestamp,
    }
    digest = hashlib.sha256(
        _canonical_json(digest_source).encode("utf-8")
    ).hexdigest()[:16]
    return f"ctx.c15c.{digest}"


def _build_trace_chain(
    *,
    module: str,
    task: str,
    context_id: str,
    workflow_id: str | None = None,
    execution: ExecutionPayloadMetadata | None = None,
) -> ExecutionPayloadTraceChain:
    capability = execution.capability if execution else None
    model = execution.model if execution else None
    key_id = execution.key_id if execution else None
    chain = tuple(
        value
        for value in (
            module,
            task,
            context_id,
            workflow_id,
            capability,
            model,
            key_id,
        )
        if value is not None
    )
    return ExecutionPayloadTraceChain(
        module=module,
        task=task,
        context_id=context_id,
        workflow_id=workflow_id,
        capability=capability,
        model=model,
        key_id=key_id,
        chain=chain,
    )


def _rejected(
    *,
    reason: str,
    module: str | None = None,
    task: str | None = None,
    context_id: str | None = None,
    workflow_id: str | None = None,
    execution: ExecutionPayloadMetadata | None = None,
    c15a_decision: WorkflowInvocationDecision | None = None,
    workflow_mapping_validated: bool = False,
    context_standardized: bool = False,
    execution_metadata_attached: bool = False,
) -> ExecutionPayloadNormalizationResult:
    trace_chain = None
    if module is not None and task is not None and context_id is not None:
        trace_chain = _build_trace_chain(
            module=module,
            task=task,
            context_id=context_id,
            workflow_id=workflow_id,
            execution=execution,
        )

    return ExecutionPayloadNormalizationResult(
        normalization_status="rejected",
        reason=reason,
        module=module,
        task=task,
        context_id=context_id,
        workflow_id=workflow_id,
        execution=execution,
        trace_chain=trace_chain,
        c15a_registered=c15a_decision.registered if c15a_decision else False,
        c15a_bound_to_module=(
            c15a_decision.bound_to_module if c15a_decision else False
        ),
        c15a_workflow_status=(
            c15a_decision.status if c15a_decision else "unregistered"
        ),
        workflow_mapping_validated=workflow_mapping_validated,
        context_standardized=context_standardized,
        execution_metadata_attached=execution_metadata_attached,
    )


def _resolve_workflow_id(
    *,
    module: str,
    requested_workflow_id: str | None,
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> tuple[str | None, WorkflowInvocationDecision, str | None]:
    if requested_workflow_id:
        decision = evaluate_workflow_invocation(
            module=module,
            workflow_id=requested_workflow_id,
            raw_workflows=raw_workflows,
        )
        if (
            decision.registered
            and decision.bound_to_module
            and decision.execution_allowed
            and decision.status == "active"
        ):
            return requested_workflow_id, decision, None
        return None, decision, decision.reason

    workflows = list_workflows_for_module(module, raw_workflows)
    active_workflows = [
        workflow for workflow in workflows if workflow.status == "active"
    ]
    if not active_workflows:
        decision = WorkflowInvocationDecision(
            module=module,
            workflow_id="[auto]",
            registered=False,
            bound_to_module=False,
            status="unregistered",
            execution_allowed=False,
            read_only=False,
            decision_mode="blocked",
            reason=(
                "C15C could not auto attach workflow_id because C15A has no "
                "active workflow bound to this module."
            ),
        )
        return None, decision, decision.reason
    if len(active_workflows) > 1:
        workflow_ids = ", ".join(
            workflow.workflow_id for workflow in active_workflows
        )
        decision = WorkflowInvocationDecision(
            module=module,
            workflow_id="[ambiguous]",
            registered=True,
            bound_to_module=True,
            status="active",
            execution_allowed=False,
            read_only=False,
            decision_mode="blocked",
            reason=(
                "C15C found multiple active C15A workflows and will not guess "
                f"a workflow_id: {workflow_ids}."
            ),
        )
        return None, decision, decision.reason

    workflow_id = active_workflows[0].workflow_id
    decision = evaluate_workflow_invocation(
        module=module,
        workflow_id=workflow_id,
        raw_workflows=raw_workflows,
    )
    if not decision.execution_allowed:
        return None, decision, decision.reason
    return workflow_id, decision, None


def _resolve_execution_metadata(
    *,
    module: str,
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> tuple[ExecutionPayloadMetadata | None, str | None]:
    try:
        routing_model = build_capability_routing_model(
            raw_capability_bindings,
            raw_module_bindings,
            raw_ai_bindings,
            raw_locks,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return (
            None,
            "C15C could not attach C14X execution metadata because the "
            f"capability binding engine is invalid: {exc}",
        )

    active_routes = [
        route
        for route in routing_model.routes
        if route.module == module and route.status == "active"
    ]
    if not active_routes:
        return (
            None,
            "C15C could not auto attach execution metadata because C14X has "
            "no active capability binding for this module.",
        )
    if len(active_routes) > 1:
        return (
            None,
            "C15C found multiple active C14X capability bindings for this "
            "module and will not guess execution metadata.",
        )

    route = active_routes[0]
    request_validation = validate_capability_binding_request(
        capability=route.capability,
        key=route.key,
        requested_model_id=route.model,
        module=module,
        raw_capability_bindings=raw_capability_bindings,
        raw_module_bindings=raw_module_bindings,
        raw_ai_bindings=raw_ai_bindings,
        raw_locks=raw_locks,
    )
    if not request_validation.valid:
        return None, request_validation.rejection_reason

    return (
        ExecutionPayloadMetadata(
            capability=route.capability,
            model=route.model,
            key_id=route.key,
        ),
        None,
    )


def normalize_execution_payload_request(
    raw_request: Mapping[str, Any],
    *,
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
    raw_capability_bindings: Sequence[CapabilityBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_module_bindings: Sequence[
        ModuleCapabilityBindingRecord | Mapping[str, Any]
    ]
    | None = None,
    raw_ai_bindings: Sequence[AIExecutionBindingRecord | Mapping[str, Any]]
    | None = None,
    raw_locks: Sequence[ModelLockRegistryRecord | Mapping[str, Any]] | None = None,
) -> ExecutionPayloadNormalizationResult:
    module: str | None = None
    task: str | None = None
    context_id: str | None = None

    try:
        if not isinstance(raw_request, Mapping):
            raise ValueError("C15C request must be a JSON object.")
        _reject_caller_execution_metadata(raw_request)
        module = _required_string_alias(raw_request, MODULE_ALIASES, "module")
        task = _required_string_alias(raw_request, TASK_ALIASES, "task")
        _validate_module(module)
        timestamp = _timestamp_from_request(raw_request)
        raw_context = _extract_alias(raw_request, CONTEXT_ALIASES)
        if raw_context is None:
            raise ValueError("C15C context_id is required.")
        context_id = standardize_context_id(
            module=module,
            task=task,
            raw_context=raw_context,
            timestamp=timestamp,
        )
        payload = _extract_payload(raw_request)
        requested_workflow_id = _string_value(raw_request.get("workflow_id"))
    except (TypeError, ValueError) as exc:
        return _rejected(
            reason=str(exc),
            module=module,
            task=task,
            context_id=context_id,
            context_standardized=context_id is not None,
        )

    try:
        workflow_id, c15a_decision, workflow_error = _resolve_workflow_id(
            module=module,
            requested_workflow_id=requested_workflow_id,
            raw_workflows=raw_workflows,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return _rejected(
            reason=(
                "C15C could not attach workflow_id because C15A workflow "
                f"mapping validation failed: {exc}"
            ),
            module=module,
            task=task,
            context_id=context_id,
            context_standardized=True,
        )

    if workflow_error or workflow_id is None:
        return _rejected(
            reason=workflow_error or "C15C workflow mapping is invalid.",
            module=module,
            task=task,
            context_id=context_id,
            workflow_id=workflow_id or requested_workflow_id,
            c15a_decision=c15a_decision,
            workflow_mapping_validated=False,
            context_standardized=True,
        )

    execution, execution_error = _resolve_execution_metadata(
        module=module,
        raw_capability_bindings=raw_capability_bindings,
        raw_module_bindings=raw_module_bindings,
        raw_ai_bindings=raw_ai_bindings,
        raw_locks=raw_locks,
    )
    if execution_error or execution is None:
        return _rejected(
            reason=execution_error or "C15C execution metadata is invalid.",
            module=module,
            task=task,
            context_id=context_id,
            workflow_id=workflow_id,
            c15a_decision=c15a_decision,
            workflow_mapping_validated=True,
            context_standardized=True,
        )

    try:
        standardized_request = ExecutionPayloadStandardRequest(
            module=module,
            task=task,
            context_id=context_id,
            workflow_id=workflow_id,
            execution=execution,
            payload=payload,
            timestamp=timestamp,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return _rejected(
            reason=f"C15C standardized request schema validation failed: {exc}",
            module=module,
            task=task,
            context_id=context_id,
            workflow_id=workflow_id,
            execution=execution,
            c15a_decision=c15a_decision,
            workflow_mapping_validated=True,
            context_standardized=True,
            execution_metadata_attached=True,
        )

    return ExecutionPayloadNormalizationResult(
        normalization_status="accepted",
        reason=(
            "C15C normalized the module request, attached C15A workflow_id, "
            "attached C14X execution metadata, standardized context_id, and "
            "stopped before any runtime execution boundary."
        ),
        module=module,
        task=task,
        context_id=context_id,
        workflow_id=workflow_id,
        execution=execution,
        standardized_request=standardized_request,
        trace_chain=_build_trace_chain(
            module=module,
            task=task,
            context_id=context_id,
            workflow_id=workflow_id,
            execution=execution,
        ),
        c15a_registered=c15a_decision.registered,
        c15a_bound_to_module=c15a_decision.bound_to_module,
        c15a_workflow_status=c15a_decision.status,
        workflow_mapping_validated=True,
        context_standardized=True,
        execution_metadata_attached=True,
        standardized_request_schema_valid=True,
    )


def get_payload_standardization_model() -> ExecutionPayloadStandardizationModel:
    return ExecutionPayloadStandardizationModel()


def get_normalization_engine_design() -> ExecutionPayloadNormalizationEngineDesign:
    return ExecutionPayloadNormalizationEngineDesign()


def get_context_standardization_rules() -> ExecutionPayloadContextRules:
    return ExecutionPayloadContextRules()


def get_workflow_mapping_integration() -> ExecutionPayloadWorkflowMappingIntegration:
    return ExecutionPayloadWorkflowMappingIntegration()


def get_execution_payload_completion_status() -> ExecutionPayloadCompletionStatus:
    return ExecutionPayloadCompletionStatus(
        proceed_reason=(
            "C15C defines the standard request model, module request "
            "normalization engine, context_id standardization rules, C15A "
            "workflow mapping integration, and C14X execution metadata "
            "attachment without runtime execution."
        )
    )
