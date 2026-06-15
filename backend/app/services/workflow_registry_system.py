from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, get_args

from pydantic import ValidationError

from ..core.workflow_registry import WORKFLOW_REGISTRY_V1
from ..schemas.workflow_registry import (
    ModuleWorkflowBinding,
    ModuleWorkflowBindingResponse,
    WorkflowInvocationDecision,
    WorkflowRegistryCompletionStatus,
    WorkflowRegistryRecord,
    WorkflowRegistryResponse,
    WorkflowRegistryRulesModel,
    WorkflowRegistryStatus,
    WorkflowRegistryValidationIssue,
    WorkflowRegistryValidationResult,
    WorkflowStatusManagementModel,
    WorkflowStatusRule,
    WorkflowSystemFlowDiagram,
)
from .module_registry import MODULE_KEY_PATTERN, list_module_manifests


WORKFLOW_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[._-][a-z][a-z0-9_]*)+$"
)
HIDDEN_N8N_WEBHOOK_REF_PATTERN = re.compile(
    r"^n8n-webhook-ref://c15a/[a-z][a-z0-9_.]*/[a-z][a-z0-9_-]*/v[0-9]+$"
)
ALLOWED_WORKFLOW_REGISTRY_STATUSES = frozenset(
    get_args(WorkflowRegistryStatus)
)
BLOCKED_WEBHOOK_MARKERS = (
    "http://",
    "https://",
    "@",
    "?",
    "#",
    "=",
    "authorization",
    "bearer ",
    "credential",
    "password",
    "secret",
    "token",
)


def _record_from_raw(
    raw: WorkflowRegistryRecord | Mapping[str, Any],
) -> WorkflowRegistryRecord:
    if isinstance(raw, WorkflowRegistryRecord):
        return raw
    return WorkflowRegistryRecord.model_validate(raw)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_workflow_id(workflow_id: str) -> None:
    if not WORKFLOW_ID_PATTERN.fullmatch(workflow_id):
        raise ValueError("C15A workflow_id must use stable lowercase segments.")
    lowered = workflow_id.lower()
    if any(marker in lowered for marker in BLOCKED_WEBHOOK_MARKERS):
        raise ValueError("C15A workflow_id contains blocked runtime data.")


def _validate_module(module: str, module_keys: set[str]) -> None:
    if not MODULE_KEY_PATTERN.fullmatch(module):
        raise ValueError("C15A module binding key is invalid.")
    if module not in module_keys:
        raise ValueError(f"C15A module is not registered: {module}")


def _validate_hidden_webhook_ref(record: WorkflowRegistryRecord) -> None:
    webhook_ref = record.n8n_webhook
    lowered = webhook_ref.lower()
    if not HIDDEN_N8N_WEBHOOK_REF_PATTERN.fullmatch(webhook_ref):
        raise ValueError(
            f"{record.workflow_id} must use an opaque n8n webhook reference."
        )
    if any(marker in lowered for marker in BLOCKED_WEBHOOK_MARKERS):
        raise ValueError(
            f"{record.workflow_id} exposes blocked n8n webhook runtime data."
        )


def _validate_timestamps(record: WorkflowRegistryRecord) -> None:
    if _parse_timestamp(record.updated_at) < _parse_timestamp(record.created_at):
        raise ValueError(f"{record.workflow_id} updated_at is before created_at.")


def validate_workflow_registry(
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> list[WorkflowRegistryRecord]:
    source = raw_workflows if raw_workflows is not None else WORKFLOW_REGISTRY_V1
    workflows = [_record_from_raw(raw) for raw in source]
    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    seen_workflow_ids: set[str] = set()
    seen_webhook_refs: set[str] = set()

    for workflow in workflows:
        _validate_workflow_id(workflow.workflow_id)
        _validate_module(workflow.module, module_keys)
        if workflow.status not in ALLOWED_WORKFLOW_REGISTRY_STATUSES:
            raise ValueError(f"{workflow.workflow_id} has invalid status.")
        if workflow.workflow_id in seen_workflow_ids:
            raise ValueError(f"Duplicate C15A workflow_id: {workflow.workflow_id}")
        if workflow.n8n_webhook in seen_webhook_refs:
            raise ValueError(
                f"Duplicate C15A hidden webhook ref: {workflow.n8n_webhook}"
            )

        _validate_hidden_webhook_ref(workflow)
        _validate_timestamps(workflow)
        seen_workflow_ids.add(workflow.workflow_id)
        seen_webhook_refs.add(workflow.n8n_webhook)

    return workflows


def list_workflow_registry(
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> WorkflowRegistryResponse:
    workflows = validate_workflow_registry(raw_workflows)
    return WorkflowRegistryResponse(
        items=workflows,
        count=len(workflows),
        active_count=sum(1 for workflow in workflows if workflow.status == "active"),
    )


def get_workflow_registry_record(
    workflow_id: str,
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> WorkflowRegistryRecord | None:
    for workflow in validate_workflow_registry(raw_workflows):
        if workflow.workflow_id == workflow_id:
            return workflow
    return None


def build_module_workflow_bindings(
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleWorkflowBindingResponse:
    workflows = validate_workflow_registry(raw_workflows)
    grouped: dict[str, list[WorkflowRegistryRecord]] = defaultdict(list)
    for workflow in workflows:
        grouped[workflow.module].append(workflow)

    bindings = [
        ModuleWorkflowBinding(
            module=module,
            workflow_ids=tuple(workflow.workflow_id for workflow in items),
            active_workflow_ids=tuple(
                workflow.workflow_id
                for workflow in items
                if workflow.status == "active"
            ),
            inactive_workflow_ids=tuple(
                workflow.workflow_id
                for workflow in items
                if workflow.status == "inactive"
            ),
            deprecated_workflow_ids=tuple(
                workflow.workflow_id
                for workflow in items
                if workflow.status == "deprecated"
            ),
            error_workflow_ids=tuple(
                workflow.workflow_id
                for workflow in items
                if workflow.status == "error"
            ),
            workflow_count=len(items),
        )
        for module, items in sorted(grouped.items())
    ]
    return ModuleWorkflowBindingResponse(items=bindings, count=len(bindings))


def list_workflows_for_module(
    module: str,
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> list[WorkflowRegistryRecord]:
    return [
        workflow
        for workflow in validate_workflow_registry(raw_workflows)
        if workflow.module == module
    ]


def get_workflow_status_management_model() -> WorkflowStatusManagementModel:
    return WorkflowStatusManagementModel(
        rules=(
            WorkflowStatusRule(
                status="active",
                execution_allowed=True,
                read_only=False,
                decision_mode="executable",
                reason=(
                    "Active workflows may be dispatched by C15B after C15A "
                    "binding validation."
                ),
            ),
            WorkflowStatusRule(
                status="inactive",
                execution_allowed=False,
                read_only=False,
                decision_mode="blocked",
                reason="Inactive workflows are registered but forbidden from execution.",
            ),
            WorkflowStatusRule(
                status="deprecated",
                execution_allowed=False,
                read_only=True,
                decision_mode="read_only",
                reason="Deprecated workflows remain queryable but cannot be dispatched.",
            ),
            WorkflowStatusRule(
                status="error",
                execution_allowed=False,
                read_only=False,
                decision_mode="blocked",
                reason="Error workflows block execution until the registry status changes.",
            ),
        )
    )


def get_workflow_registry_rules_model() -> WorkflowRegistryRulesModel:
    return WorkflowRegistryRulesModel()


def evaluate_workflow_invocation(
    *,
    module: str,
    workflow_id: str,
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> WorkflowInvocationDecision:
    workflow = get_workflow_registry_record(workflow_id, raw_workflows)
    if workflow is None:
        return WorkflowInvocationDecision(
            module=module,
            workflow_id=workflow_id,
            registered=False,
            bound_to_module=False,
            status="unregistered",
            execution_allowed=False,
            read_only=False,
            decision_mode="blocked",
            reason="Unregistered workflows are blocked by the C15A registry.",
        )

    if workflow.module != module:
        return WorkflowInvocationDecision(
            module=module,
            workflow_id=workflow_id,
            registered=True,
            bound_to_module=False,
            status=workflow.status,
            execution_allowed=False,
            read_only=False,
            decision_mode="blocked",
            reason=(
                "The workflow is registered but not explicitly bound to the "
                "requested module."
            ),
        )

    if workflow.status == "active":
        return WorkflowInvocationDecision(
            module=module,
            workflow_id=workflow_id,
            registered=True,
            bound_to_module=True,
            status=workflow.status,
            execution_allowed=True,
            read_only=False,
            decision_mode="executable",
            hidden_webhook_ref=workflow.n8n_webhook,
            reason=(
                "Workflow is active and explicitly bound; C15B may use the "
                "hidden webhook reference."
            ),
        )

    if workflow.status == "deprecated":
        return WorkflowInvocationDecision(
            module=module,
            workflow_id=workflow_id,
            registered=True,
            bound_to_module=True,
            status=workflow.status,
            execution_allowed=False,
            read_only=True,
            decision_mode="read_only",
            hidden_webhook_ref=workflow.n8n_webhook,
            reason="Deprecated workflows are read-only and cannot be dispatched.",
        )

    reason = (
        "Inactive workflows are forbidden from execution."
        if workflow.status == "inactive"
        else "Workflows in error status block execution."
    )
    return WorkflowInvocationDecision(
        module=module,
        workflow_id=workflow_id,
        registered=True,
        bound_to_module=True,
        status=workflow.status,
        execution_allowed=False,
        read_only=False,
        decision_mode="blocked",
        hidden_webhook_ref=workflow.n8n_webhook,
        reason=reason,
    )


def _validation_issue(
    *,
    code: str,
    message: str,
    workflow_id: str | None = None,
    module: str | None = None,
    severity: str = "error",
) -> WorkflowRegistryValidationIssue:
    return WorkflowRegistryValidationIssue(
        severity=severity,
        code=code,
        message=message,
        workflow_id=workflow_id,
        module=module,
    )


def build_workflow_registry_validation_result(
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> WorkflowRegistryValidationResult:
    try:
        workflows = validate_workflow_registry(raw_workflows)
    except (TypeError, ValueError, ValidationError) as exc:
        return WorkflowRegistryValidationResult(
            valid=False,
            issues=[
                _validation_issue(
                    code="c15a_workflow_registry_invalid",
                    message=str(exc),
                )
            ],
            workflow_count=0,
            module_binding_count=0,
            active_workflow_count=0,
        )

    modules = {workflow.module for workflow in workflows}
    return WorkflowRegistryValidationResult(
        valid=True,
        issues=[],
        workflow_count=len(workflows),
        module_binding_count=len(modules),
        active_workflow_count=sum(
            1 for workflow in workflows if workflow.status == "active"
        ),
    )


def get_workflow_system_flow_diagram() -> WorkflowSystemFlowDiagram:
    return WorkflowSystemFlowDiagram()


def get_workflow_registry_completion_status() -> WorkflowRegistryCompletionStatus:
    return WorkflowRegistryCompletionStatus(
        proceed_reason=(
            "C15A defines the workflow registry model, explicit module bindings, "
            "status decisions, hidden webhook references, and read-only flow "
            "contract required before C15B."
        )
    )
