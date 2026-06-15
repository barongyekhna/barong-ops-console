from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...models.user import User
from ...schemas.workflow_registry import (
    ModuleWorkflowBindingResponse,
    WorkflowInvocationDecision,
    WorkflowRegistryCompletionStatus,
    WorkflowRegistryRecord,
    WorkflowRegistryResponse,
    WorkflowRegistryRulesModel,
    WorkflowRegistryValidationResult,
    WorkflowStatusManagementModel,
    WorkflowSystemFlowDiagram,
)
from ...services.workflow_registry_system import (
    build_module_workflow_bindings,
    build_workflow_registry_validation_result,
    evaluate_workflow_invocation,
    get_workflow_registry_completion_status,
    get_workflow_registry_record,
    get_workflow_registry_rules_model,
    get_workflow_status_management_model,
    get_workflow_system_flow_diagram,
    list_workflow_registry,
    list_workflows_for_module,
)
from ..deps import require_rbac

router = APIRouter(
    prefix="/workflow-registry",
    tags=["workflow-registry"],
)


@router.get("/registry", response_model=WorkflowRegistryResponse)
def workflow_registry(
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowRegistryResponse:
    del user
    return list_workflow_registry()


@router.get("/workflows/{workflow_id}", response_model=WorkflowRegistryRecord)
def workflow_registry_detail(
    workflow_id: str,
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowRegistryRecord:
    del user
    workflow = get_workflow_registry_record(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow is not registered in C15A.",
        )
    return workflow


@router.get("/module-bindings", response_model=ModuleWorkflowBindingResponse)
def workflow_registry_module_bindings(
    user: User = Depends(require_rbac("C15A", "execute")),
) -> ModuleWorkflowBindingResponse:
    del user
    return build_module_workflow_bindings()


@router.get(
    "/modules/{module}/workflows",
    response_model=WorkflowRegistryResponse,
)
def workflow_registry_module_workflows(
    module: str,
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowRegistryResponse:
    del user
    workflows = list_workflows_for_module(module)
    return WorkflowRegistryResponse(
        items=workflows,
        count=len(workflows),
        active_count=sum(
            1 for workflow in workflows if workflow.status == "active"
        ),
    )


@router.get("/status-management", response_model=WorkflowStatusManagementModel)
def workflow_registry_status_management(
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowStatusManagementModel:
    del user
    return get_workflow_status_management_model()


@router.get("/rules", response_model=WorkflowRegistryRulesModel)
def workflow_registry_rules(
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowRegistryRulesModel:
    del user
    return get_workflow_registry_rules_model()


@router.get("/decision", response_model=WorkflowInvocationDecision)
def workflow_registry_decision(
    module: str = Query(min_length=1, max_length=128),
    workflow_id: str = Query(min_length=1, max_length=180),
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowInvocationDecision:
    del user
    return evaluate_workflow_invocation(module=module, workflow_id=workflow_id)


@router.get("/validation", response_model=WorkflowRegistryValidationResult)
def workflow_registry_validation(
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowRegistryValidationResult:
    del user
    return build_workflow_registry_validation_result()


@router.get("/system-flow", response_model=WorkflowSystemFlowDiagram)
def workflow_registry_system_flow(
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowSystemFlowDiagram:
    del user
    return get_workflow_system_flow_diagram()


@router.get(
    "/completion-status",
    response_model=WorkflowRegistryCompletionStatus,
)
def workflow_registry_completion_status(
    user: User = Depends(require_rbac("C15A", "execute")),
) -> WorkflowRegistryCompletionStatus:
    del user
    return get_workflow_registry_completion_status()
