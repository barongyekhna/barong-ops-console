from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..schemas.module_workflow_binding import (
    ModuleWorkflowAccessControlSystem,
    ModuleWorkflowBindingCompletionStatus,
    ModuleWorkflowBindingDecision,
    ModuleWorkflowBindingModel,
    ModuleWorkflowBindingRecord,
    ModuleWorkflowBindingStatus,
    ModuleWorkflowBindingValidationIssue,
    ModuleWorkflowBindingValidationResult,
    ModuleWorkflowEnforcementRules,
    ModuleWorkflowIsolationRules,
)
from ..schemas.workflow_registry import WorkflowRegistryRecord
from .module_registry import MODULE_KEY_PATTERN, list_module_manifests
from .workflow_registry_system import (
    WORKFLOW_ID_PATTERN,
    validate_workflow_registry,
)


INVALID_REQUEST_MODULE = "[invalid_module]"
INVALID_REQUEST_WORKFLOW = "[invalid_workflow]"


def _binding_status_for(
    workflows: Sequence[WorkflowRegistryRecord],
) -> ModuleWorkflowBindingStatus:
    if any(workflow.status == "active" for workflow in workflows):
        return "active"
    if any(workflow.status == "deprecated" for workflow in workflows):
        return "read_only"
    return "blocked"


def _safe_request_module_id(module_id: str) -> str | None:
    if not MODULE_KEY_PATTERN.fullmatch(module_id):
        return None
    return module_id


def _safe_request_workflow_id(workflow_id: str) -> str | None:
    if not WORKFLOW_ID_PATTERN.fullmatch(workflow_id):
        return None
    return workflow_id


def build_module_workflow_binding_model(
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleWorkflowBindingModel:
    workflows = validate_workflow_registry(raw_workflows)
    workflows_by_module: dict[str, list[WorkflowRegistryRecord]] = defaultdict(list)
    for workflow in workflows:
        workflows_by_module[workflow.module].append(workflow)

    bindings: list[ModuleWorkflowBindingRecord] = []
    for manifest in sorted(list_module_manifests(), key=lambda item: item.module_key):
        module_workflows = sorted(
            workflows_by_module.get(manifest.module_key, []),
            key=lambda item: item.workflow_id,
        )
        allowed_workflows = tuple(
            workflow.workflow_id
            for workflow in module_workflows
            if workflow.status == "active"
        )
        read_only_workflows = tuple(
            workflow.workflow_id
            for workflow in module_workflows
            if workflow.status == "deprecated"
        )
        blocked_workflows = tuple(
            workflow.workflow_id
            for workflow in module_workflows
            if workflow.status in {"inactive", "error"}
        )
        bindings.append(
            ModuleWorkflowBindingRecord(
                module_id=manifest.module_key,
                allowed_workflows=allowed_workflows,
                binding_status=_binding_status_for(module_workflows),
                registered_workflows=tuple(
                    workflow.workflow_id for workflow in module_workflows
                ),
                read_only_workflows=read_only_workflows,
                blocked_workflows=blocked_workflows,
            )
        )

    return ModuleWorkflowBindingModel(
        items=bindings,
        count=len(bindings),
        active_binding_count=sum(
            1 for binding in bindings if binding.binding_status == "active"
        ),
        read_only_binding_count=sum(
            1 for binding in bindings if binding.binding_status == "read_only"
        ),
        blocked_binding_count=sum(
            1 for binding in bindings if binding.binding_status == "blocked"
        ),
        allowed_workflow_count=sum(
            len(binding.allowed_workflows) for binding in bindings
        ),
    )


def validate_module_workflow_binding_engine(
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> tuple[list[ModuleWorkflowBindingRecord], list[WorkflowRegistryRecord]]:
    workflows = validate_workflow_registry(raw_workflows)
    binding_model = build_module_workflow_binding_model(raw_workflows)
    workflow_by_id = {workflow.workflow_id: workflow for workflow in workflows}
    seen_allowed_workflows: dict[str, str] = {}

    for binding in binding_model.items:
        for workflow_id in binding.allowed_workflows:
            workflow = workflow_by_id.get(workflow_id)
            if workflow is None:
                raise ValueError(
                    f"C15F allowed workflow is not registered in C15A: {workflow_id}"
                )
            if workflow.module != binding.module_id:
                raise ValueError(
                    "C15F module workflow isolation violation: "
                    f"{binding.module_id} lists {workflow_id} owned by "
                    f"{workflow.module}."
                )
            if workflow.status != "active":
                raise ValueError(
                    "C15F allowed workflow must be active in C15A: "
                    f"{workflow_id}"
                )

            existing_module = seen_allowed_workflows.get(workflow_id)
            if existing_module is not None and existing_module != binding.module_id:
                raise ValueError(
                    "C15F cross-module workflow binding violation: "
                    f"{workflow_id} is listed by both {existing_module} "
                    f"and {binding.module_id}."
                )
            seen_allowed_workflows[workflow_id] = binding.module_id

        if binding.binding_status == "active" and not binding.allowed_workflows:
            raise ValueError(
                f"C15F active binding has no allowed workflows: {binding.module_id}"
            )
        if binding.binding_status != "active" and binding.allowed_workflows:
            raise ValueError(
                "C15F non-active binding cannot expose allowed workflows: "
                f"{binding.module_id}"
            )

    return binding_model.items, workflows


def get_module_workflow_enforcement_rules() -> ModuleWorkflowEnforcementRules:
    return ModuleWorkflowEnforcementRules()


def get_module_workflow_access_control_system() -> ModuleWorkflowAccessControlSystem:
    return ModuleWorkflowAccessControlSystem()


def get_module_workflow_isolation_rules() -> ModuleWorkflowIsolationRules:
    return ModuleWorkflowIsolationRules()


def _decision(
    *,
    module_id: str,
    workflow_id: str,
    module_registered: bool,
    registered_in_c15a: bool,
    module_binding_found: bool,
    workflow_owned_by_module: bool,
    workflow_in_module_whitelist: bool,
    binding_status: ModuleWorkflowBindingStatus | str,
    workflow_registry_status: str,
    workflow_access_allowed: bool,
    binding_validation_passed: bool,
    isolation_violation: bool,
    execution_rejected: bool,
    rejection_code: str | None,
    reason: str,
) -> ModuleWorkflowBindingDecision:
    return ModuleWorkflowBindingDecision(
        module_id=module_id,
        workflow_id=workflow_id,
        module_registered=module_registered,
        registered_in_c15a=registered_in_c15a,
        module_binding_found=module_binding_found,
        workflow_owned_by_module=workflow_owned_by_module,
        workflow_in_module_whitelist=workflow_in_module_whitelist,
        binding_status=binding_status,
        workflow_registry_status=workflow_registry_status,
        workflow_access_allowed=workflow_access_allowed,
        binding_validation_passed=binding_validation_passed,
        isolation_violation=isolation_violation,
        execution_rejected=execution_rejected,
        rejection_code=rejection_code,
        reason=reason,
    )


def _rejection(
    *,
    module_id: str,
    workflow_id: str,
    rejection_code: str,
    reason: str,
    module_registered: bool = False,
    registered_in_c15a: bool = False,
    module_binding_found: bool = False,
    workflow_owned_by_module: bool = False,
    workflow_in_module_whitelist: bool = False,
    binding_status: ModuleWorkflowBindingStatus | str = "missing",
    workflow_registry_status: str = "unregistered",
    isolation_violation: bool = False,
) -> ModuleWorkflowBindingDecision:
    return _decision(
        module_id=module_id,
        workflow_id=workflow_id,
        module_registered=module_registered,
        registered_in_c15a=registered_in_c15a,
        module_binding_found=module_binding_found,
        workflow_owned_by_module=workflow_owned_by_module,
        workflow_in_module_whitelist=workflow_in_module_whitelist,
        binding_status=binding_status,
        workflow_registry_status=workflow_registry_status,
        workflow_access_allowed=False,
        binding_validation_passed=False,
        isolation_violation=isolation_violation,
        execution_rejected=True,
        rejection_code=rejection_code,
        reason=reason,
    )


def evaluate_module_workflow_access(
    *,
    module_id: str,
    workflow_id: str,
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleWorkflowBindingDecision:
    safe_module_id = _safe_request_module_id(module_id)
    safe_workflow_id = _safe_request_workflow_id(workflow_id)
    if safe_module_id is None or safe_workflow_id is None:
        return _rejection(
            module_id=safe_module_id or INVALID_REQUEST_MODULE,
            workflow_id=safe_workflow_id or INVALID_REQUEST_WORKFLOW,
            rejection_code="c15f_module_workflow_request_invalid",
            reason=(
                "Execution rejected because module_id or workflow_id does not "
                "match the C15F identifier policy."
            ),
        )

    try:
        bindings, workflows = validate_module_workflow_binding_engine(
            raw_workflows
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return _rejection(
            module_id=safe_module_id,
            workflow_id=safe_workflow_id,
            rejection_code="c15f_module_workflow_binding_engine_invalid",
            reason=str(exc),
        )

    module_keys = {manifest.module_key for manifest in list_module_manifests()}
    module_registered = safe_module_id in module_keys
    binding_by_module = {binding.module_id: binding for binding in bindings}
    workflow_by_id = {workflow.workflow_id: workflow for workflow in workflows}
    binding = binding_by_module.get(safe_module_id)
    workflow = workflow_by_id.get(safe_workflow_id)

    if not module_registered:
        return _rejection(
            module_id=safe_module_id,
            workflow_id=safe_workflow_id,
            rejection_code="c15f_module_not_registered",
            reason="Execution rejected because the module is not registered.",
        )

    if workflow is None:
        return _rejection(
            module_id=safe_module_id,
            workflow_id=safe_workflow_id,
            rejection_code="c15f_workflow_not_registered",
            reason=(
                "Execution rejected because the workflow is not registered in "
                "the C15A Workflow Registry."
            ),
            module_registered=True,
            module_binding_found=binding is not None,
            binding_status=(
                binding.binding_status if binding is not None else "missing"
            ),
        )

    if binding is None:
        return _rejection(
            module_id=safe_module_id,
            workflow_id=safe_workflow_id,
            rejection_code="c15f_module_binding_missing",
            reason=(
                "Execution rejected because the module has no C15F workflow "
                "binding record."
            ),
            module_registered=True,
            registered_in_c15a=True,
            workflow_registry_status=workflow.status,
        )

    if workflow.module != safe_module_id:
        return _rejection(
            module_id=safe_module_id,
            workflow_id=safe_workflow_id,
            rejection_code="c15f_cross_module_workflow_call_blocked",
            reason=(
                "Execution rejected because the workflow is registered for a "
                "different module."
            ),
            module_registered=True,
            registered_in_c15a=True,
            module_binding_found=True,
            binding_status=binding.binding_status,
            workflow_registry_status=workflow.status,
            isolation_violation=True,
        )

    workflow_in_whitelist = safe_workflow_id in binding.allowed_workflows
    if not workflow_in_whitelist:
        return _rejection(
            module_id=safe_module_id,
            workflow_id=safe_workflow_id,
            rejection_code="c15f_workflow_not_allowed_for_module",
            reason=(
                "Execution rejected because the workflow is not in the "
                "module's C15F allowed_workflows whitelist."
            ),
            module_registered=True,
            registered_in_c15a=True,
            module_binding_found=True,
            workflow_owned_by_module=True,
            workflow_in_module_whitelist=False,
            binding_status=binding.binding_status,
            workflow_registry_status=workflow.status,
        )

    if binding.binding_status != "active" or workflow.status != "active":
        return _rejection(
            module_id=safe_module_id,
            workflow_id=safe_workflow_id,
            rejection_code="c15f_workflow_binding_not_active",
            reason=(
                "Execution rejected because the module binding or workflow "
                "status is not active."
            ),
            module_registered=True,
            registered_in_c15a=True,
            module_binding_found=True,
            workflow_owned_by_module=True,
            workflow_in_module_whitelist=True,
            binding_status=binding.binding_status,
            workflow_registry_status=workflow.status,
        )

    return _decision(
        module_id=safe_module_id,
        workflow_id=safe_workflow_id,
        module_registered=True,
        registered_in_c15a=True,
        module_binding_found=True,
        workflow_owned_by_module=True,
        workflow_in_module_whitelist=True,
        binding_status=binding.binding_status,
        workflow_registry_status=workflow.status,
        workflow_access_allowed=True,
        binding_validation_passed=True,
        isolation_violation=False,
        execution_rejected=False,
        rejection_code=None,
        reason=(
            "C15F binding validation passed for an active workflow in the "
            "module whitelist. C15F performs no runtime execution."
        ),
    )


def _validation_issue(
    *,
    code: str,
    message: str,
    module_id: str | None = None,
    workflow_id: str | None = None,
    severity: str = "error",
) -> ModuleWorkflowBindingValidationIssue:
    return ModuleWorkflowBindingValidationIssue(
        severity=severity,
        code=code,
        message=message,
        module_id=module_id,
        workflow_id=workflow_id,
    )


def build_module_workflow_binding_validation_result(
    raw_workflows: Sequence[WorkflowRegistryRecord | Mapping[str, Any]]
    | None = None,
) -> ModuleWorkflowBindingValidationResult:
    c15a_registry_workflow_count = 0
    try:
        workflows = validate_workflow_registry(raw_workflows)
        c15a_registry_workflow_count = len(workflows)
        bindings, _ = validate_module_workflow_binding_engine(raw_workflows)
    except (TypeError, ValueError, ValidationError) as exc:
        return ModuleWorkflowBindingValidationResult(
            valid=False,
            issues=[
                _validation_issue(
                    code="c15f_module_workflow_binding_invalid",
                    message=str(exc),
                )
            ],
            module_binding_count=0,
            active_module_binding_count=0,
            read_only_module_binding_count=0,
            blocked_module_binding_count=0,
            allowed_workflow_count=0,
            c15a_registry_workflow_count=c15a_registry_workflow_count,
        )

    return ModuleWorkflowBindingValidationResult(
        valid=True,
        issues=[],
        module_binding_count=len(bindings),
        active_module_binding_count=sum(
            1 for binding in bindings if binding.binding_status == "active"
        ),
        read_only_module_binding_count=sum(
            1 for binding in bindings if binding.binding_status == "read_only"
        ),
        blocked_module_binding_count=sum(
            1 for binding in bindings if binding.binding_status == "blocked"
        ),
        allowed_workflow_count=sum(
            len(binding.allowed_workflows) for binding in bindings
        ),
        c15a_registry_workflow_count=len(workflows),
    )


def get_module_workflow_binding_completion_status() -> ModuleWorkflowBindingCompletionStatus:
    return ModuleWorkflowBindingCompletionStatus(
        proceed_reason=(
            "C15F defines module_id, allowed_workflows, binding_status, "
            "strict whitelist enforcement, C15A registry access control, and "
            "cross-module workflow isolation without runtime execution."
        )
    )
